"""Memory estimates, real wire boundaries and incomplete download recovery."""
from dataclasses import replace
import json
from pathlib import Path
import struct
from types import SimpleNamespace

import pytest

from AI.processors import local_runtime, local_transport, pipeline
from AI.processors.gguf_metadata import read_gguf_metadata, InvalidGGUF
from AI.processors.local_resources import GIB, ResourceSnapshot, build_local_resource_plan


def gguf(architecture="qwen3", extra=None):
    fields = {"general.architecture": architecture, architecture + ".block_count": 32,
        architecture + ".context_length": 32768, architecture + ".attention.head_count": 32,
        architecture + ".attention.head_count_kv": 4, architecture + ".embedding_length": 4096,
        **(extra or {})}
    def string(text):
        raw = text.encode()
        return struct.pack("<Q", len(raw)) + raw
    out = b"GGUF" + struct.pack("<IQQ", 3, 100, len(fields))
    for key, value in fields.items():
        out += string(key)
        if isinstance(value, str):
            out += struct.pack("<I", 8) + string(value)
        else:
            out += struct.pack("<II", 4, value)
    return out


def hardware(**values):
    return ResourceSnapshot(**{"total_ram_bytes": 16*GIB, "available_ram_bytes": 7*GIB,
        "cpu_count": 16, "gpu_total_vram_bytes": 4*GIB, "gpu_free_vram_bytes": 4*GIB,
        "disk_free_bytes": 20*GIB, "virtual_available_bytes": 16*GIB, **values})


def test_real_gguf_metadata_overrides_marketing_filename_and_blocks_helper(tmp_path):
    path = tmp_path / "DeepSeek-Flash-9B.gguf"
    path.write_bytes(gguf("deepseek4_mtp_support"))
    plan = build_local_resource_plan({"local_path": str(path)}, snapshot=hardware())
    assert plan.architecture == "deepseek4_mtp_support"
    assert not plan.safe_to_run and plan.suitability == "blocked"


@pytest.mark.parametrize("body", [b"", b"not-a-model", b"GGUF" + struct.pack("<IQQ",3,1,1)])
def test_malformed_gguf_is_rejected_before_startup(tmp_path, body):
    path = tmp_path / "model.gguf"
    path.write_bytes(body)
    with pytest.raises(InvalidGGUF):
        read_gguf_metadata(path)
    assert not build_local_resource_plan({"local_path": str(path)}, snapshot=hardware()).safe_to_run


def test_gguf_cache_refreshes_after_file_is_replaced(tmp_path):
    path = tmp_path / "model.gguf"
    path.write_bytes(gguf("qwen3"))
    assert read_gguf_metadata(path)["general.architecture"] == "qwen3"
    path.write_bytes(gguf("gemma4"))
    assert read_gguf_metadata(path)["general.architecture"] == "gemma4"


def test_disk_space_does_not_become_memory_or_override_commit_shortage():
    record = {"filename": "Qwen-9B-Q4_K_M.gguf", "size_bytes": 6*GIB}
    scarce = hardware(available_ram_bytes=GIB, virtual_available_bytes=GIB, disk_free_bytes=500*GIB)
    plan = build_local_resource_plan(record, snapshot=scarce)
    assert not plan.safe_to_run
    assert plan.disk_budget_bytes == 0


def test_large_model_can_page_weights_without_cutting_agent_context():
    record = {"filename": "gpt-oss-20b.gguf", "size_bytes": 12*GIB}
    plan = build_local_resource_plan(record, snapshot=hardware())
    assert plan.safe_to_run and plan.requires_paging
    assert plan.num_ctx >= 8192 and plan.max_tokens >= 1024
    assert plan.use_mmap and not plan.trim_working_set and not plan.use_mlock
    assert plan.suitability == "slow"


def test_explicit_zero_gpu_and_max_context_are_respected_without_unsafe_override():
    record = {"size_bytes": 3*GIB, "runtime_config": {"num_gpu": 0, "num_ctx": 16384,
        "performance_preset": "quality", "allow_unsafe": True}}
    plan = build_local_resource_plan(record, snapshot=hardware())
    assert plan.num_gpu == 0 and plan.num_ctx == 16384
    assert not plan.allow_unsafe


def test_unknown_model_size_is_not_advertised_as_safe():
    plan = build_local_resource_plan({"filename": "mystery.gguf"}, snapshot=hardware())
    assert plan.suitability == "unknown" and not plan.safe_to_run


def test_cpu_binary_explicitly_disables_automatic_gpu_and_bounds_caches():
    plan = build_local_resource_plan({"size_bytes": 3*GIB}, snapshot=hardware())
    args = local_runtime._llama_server_args(executable="/windows-x64-cpu/llama-server.exe",
        model_path="/model.gguf", host="127.0.0.1", port=1234, plan=plan)
    assert args[args.index("-ngl")+1] == "0"
    assert args[args.index("--cache-ram")+1] == "0"
    assert args[args.index("--parallel")+1] == "1"
    assert "--jinja" in args and "--mlock" not in args


@pytest.mark.parametrize("url", ["https://127.0.0.1:80", "http://example.com", "http://127.0.0.1.evil.test"])
def test_local_transport_never_connects_to_an_external_provider(url):
    with pytest.raises(ValueError):
        local_transport.build_local_http_client(base_url=url, model="test", plan=None)


class Response:
    ok = True
    def __init__(self, data): self.data = data
    def json(self): return self.data


def transport(monkeypatch, *, prompt_tokens=100, finish="stop"):
    sent = []
    class Session:
        trust_env = True
        def post(self, url, json, timeout):
            sent.append((url,json,timeout))
            if url.endswith("/apply-template"): return Response({"prompt":"FULL ORIGINAL PROMPT AND TOOLS"})
            if url.endswith("/tokenize"): return Response({"tokens": list(range(prompt_tokens))})
            return Response({"choices":[{"finish_reason":finish,"message":{"content":"Türkçe gerçek yanıt",
                "tool_calls": [{"function":{"name":"orders_summary","arguments":'{"period":"all"}'}}]
                if json.get("tools") else []}}],"usage":{"prompt_tokens":prompt_tokens}})
        def close(self): pass
    monkeypatch.setattr(local_transport.requests,"Session",Session)
    plan = build_local_resource_plan({"size_bytes": 3*GIB}, snapshot=hardware())
    client = local_transport.build_local_http_client(base_url="http://127.0.0.1:1234",model="test",
        plan=plan,record={"temperature":0.7,"top_p":0.9,"top_k":25,"seed":7})
    return client, sent, plan


def test_native_local_tools_reach_selected_model_and_return_original_name(monkeypatch):
    client,sent,plan = transport(monkeypatch)
    response = client.invoke_tools("COMPLETE ORIGINAL INPUT",tools=[{"name":"orders.summary",
        "description":"Read orders", "parameters":{"type":"object","properties":{}}}])
    assert json.loads(response)["tool"] == "orders.summary"
    request = sent[-1][1]
    assert request["messages"][0]["content"] == "COMPLETE ORIGINAL INPUT"
    assert request["max_tokens"] == plan.max_tokens
    assert request["top_p"] == 0.9 and request["seed"] == 7
    assert sent[-1][2][1] >= 3600
    assert client.resource_plan["capability_profile"]["native_tool_runtime_enabled"]


def test_context_overflow_is_measured_with_real_tokenizer_before_generation(monkeypatch):
    client,sent,plan = transport(monkeypatch,prompt_tokens=12000)
    with pytest.raises(local_transport.LocalContextExceeded,match="içerik kesilmedi"):
        client("KEEP THIS WHOLE PROMPT")
    assert not any(url.endswith('/v1/chat/completions') for url,_,_ in sent)
    assert not client.resource_plan["prompt_compacted"]


def test_truncated_generation_never_becomes_a_tool_call_or_completed_answer(monkeypatch):
    client,_,_ = transport(monkeypatch,finish="length")
    with pytest.raises(local_transport.LocalGenerationIncomplete):
        client("generate")


def test_auto_config_discards_old_tiny_computed_defaults(monkeypatch):
    monkeypatch.setattr(pipeline,"_default_runtime_config",lambda record:{"performance_preset":"auto","num_ctx":8192})
    monkeypatch.setattr(pipeline,"_model_config_key",lambda record:"model")
    config=pipeline._merge_runtime_config({}, {"model_runtime_configs":{"model":{"num_ctx":512,"num_gpu":0}}})
    assert "num_ctx" not in config and "num_gpu" not in config


def test_quality_config_keeps_explicit_settings(monkeypatch):
    monkeypatch.setattr(pipeline,"_default_runtime_config",lambda record:{"performance_preset":"auto","num_ctx":8192})
    monkeypatch.setattr(pipeline,"_model_config_key",lambda record:"model")
    config=pipeline._merge_runtime_config({}, {"model_runtime_configs":{"model":{
        "performance_preset":"quality","num_ctx":16384,"num_gpu":0}}})
    assert config["num_ctx"] == 16384 and config["num_gpu"] == 0


class DownloadResponse:
    def __init__(self, body, headers, status=200):
        self.body, self.headers, self.status_code = body, headers, status
    def __enter__(self): return self
    def __exit__(self,*args): pass
    def raise_for_status(self): pass
    def iter_content(self, chunk_size): yield self.body


@pytest.mark.parametrize("body,total", [(b"short",100), (b"not-a-gguf",10)])
def test_incomplete_or_invalid_download_never_enters_installed_registry(tmp_path,monkeypatch,body,total):
    monkeypatch.setattr(pipeline.requests,"get",lambda *a,**k:DownloadResponse(body,{"Content-Length":str(total)}))
    registrations=[]
    monkeypatch.setattr(pipeline,"_upsert_installed_model",lambda **values:registrations.append(values))
    result=pipeline.download_hf_model_file(repo_id="test/model",filename="model.gguf",download_root=str(tmp_path))
    assert not result.success and not registrations
    assert (tmp_path/"test"/"model"/"model.gguf.part").exists()
    assert not (tmp_path/"test"/"model"/"model.gguf").exists()


def test_resume_rejects_wrong_byte_range_without_overwriting_partial(tmp_path,monkeypatch):
    part=tmp_path/"test"/"model"/"model.gguf.part"
    part.parent.mkdir(parents=True)
    part.write_bytes(b"original")
    response=DownloadResponse(b"replacement",{"Content-Length":"11","Content-Range":"bytes 0-10/19"},206)
    monkeypatch.setattr(pipeline.requests,"get",lambda *a,**k:response)
    result=pipeline.download_hf_model_file(repo_id="test/model",filename="model.gguf",download_root=str(tmp_path))
    assert not result.success and part.read_bytes()==b"original"


def test_download_registers_only_complete_gguf_after_atomic_rename(tmp_path,monkeypatch):
    body=gguf()
    monkeypatch.setattr(pipeline.requests,"get",lambda *a,**k:DownloadResponse(body,{"Content-Length":str(len(body))}))
    registrations=[]
    def register(**values):
        assert Path(values["local_path"]).read_bytes()==body
        registrations.append(values)
        return values
    monkeypatch.setattr(pipeline,"_upsert_installed_model",register)
    result=pipeline.download_hf_model_file(repo_id="test/model",filename="model.gguf",download_root=str(tmp_path))
    assert result.success and len(registrations)==1
    assert not (tmp_path/"test"/"model"/"model.gguf.part").exists()


def test_small_tool_menu_keeps_best_discovery_results_first():
    from AI.runtime.catalog import select_tool_menu,record_discovered_tools
    from AI.processors.tools import registered_tools
    from AI.processors.session_state import AgentSessionState
    registry=registered_tools()
    state=AgentSessionState(goal="inspect")
    state.active_entities["model_loop"]={}
    found=["orders.summary","orders.count","orders.query","orders.snapshot","stock.low_stock"]
    record_discovered_tools(state,{"operations":[{"exposed_tool_name":name} for name in found]},registry)
    menu=select_tool_menu(registry,state,limit=4)
    assert "orders.summary" in menu and "stock.low_stock" not in menu


def test_report_tool_is_visible_even_when_many_alternative_producers_do_not_fit():
    from AI.runtime.catalog import select_tool_menu,record_discovered_tools
    from AI.processors.tools import registered_tools
    from AI.processors.session_state import AgentSessionState
    registry=registered_tools()
    state=AgentSessionState(goal="report")
    state.active_entities["model_loop"]={}
    record_discovered_tools(state,{"operations":[{"exposed_tool_name":"reports.build_snapshot"}]},registry)
    menu=select_tool_menu(registry,state,limit=3)
    assert "reports.build_snapshot" in menu and len(menu)<=3


def test_pause_interrupts_slow_local_generation_and_next_call_restarts(monkeypatch):
    import threading
    from AI.processors.task_control import AgentTaskControl
    control=AgentTaskControl()
    waiting=threading.Event()
    release=threading.Event()
    counters={"cancel":0,"restart":0}
    class Session:
        def post(self,url,json,timeout):
            if url.endswith('/apply-template'):return Response({"prompt":"whole input"})
            if url.endswith('/tokenize'):return Response({"tokens":[1,2]})
            if not release.is_set():
                waiting.set()
                assert release.wait(5)
            return Response({"choices":[{"finish_reason":"stop","message":{"content":"Devam ettim."}}]})
        def close(self):pass
    monkeypatch.setattr(local_transport.requests,"Session",Session)
    plan=build_local_resource_plan({"size_bytes":3*GIB},snapshot=hardware())
    client=local_transport.build_local_http_client(base_url='http://127.0.0.1:1234',model='test',plan=plan)
    client.task_control=control
    def cancel():
        counters['cancel']+=1
        release.set()
    def restart():
        counters['restart']+=1
        return 'http://127.0.0.1:5678'
    client.cancel_generation=cancel
    client.restart_runtime=restart
    def pause():
        assert waiting.wait(5)
        control.request_pause()
    watcher=threading.Thread(target=pause)
    watcher.start()
    with pytest.raises(local_transport.LocalGenerationCancelled):client('slow request')
    watcher.join(5)
    assert counters['cancel']==1 and client.resource_plan['restart_required']
    client.task_control=None
    assert client('continue')=='Devam ettim.'
    assert counters['restart']==1 and not client.resource_plan['restart_required']


def test_partial_http_range_does_not_look_like_complete_model(tmp_path,monkeypatch):
    body=gguf()
    response=DownloadResponse(body,{'Content-Length':str(len(body)),
        'Content-Range':f'bytes 0-{len(body)-1}/{len(body)+1000}'},206)
    monkeypatch.setattr(pipeline.requests,'get',lambda *a,**kw:response)
    result=pipeline.download_hf_model_file(repo_id='test/model',filename='model.gguf',download_root=str(tmp_path))
    assert not result.success and (tmp_path/'test'/'model'/'model.gguf.part').exists()
    assert not (tmp_path/'test'/'model'/'model.gguf').exists()


def test_gpu_allocation_failure_retries_same_model_and_context_with_less_offload(monkeypatch):
    plan=build_local_resource_plan({'size_bytes':3*GIB},snapshot=hardware())
    attempts=[]
    monkeypatch.setattr(local_runtime,'find_bundled_llama_server',lambda:'/runner.exe')
    monkeypatch.setattr(local_runtime,'_record_model_path',lambda record:'/Qwen.gguf')
    def resource_plan(record,**kwargs):
        config=record.get('runtime_config') or {}
        return replace(plan,num_gpu=config.get('num_gpu',plan.num_gpu))
    monkeypatch.setattr(local_runtime,'build_local_resource_plan',resource_plan)
    def start(**kwargs):
        attempts.append(kwargs)
        if len(attempts)==1:raise RuntimeError('CUDA out of memory')
        return SimpleNamespace(key='resumed',base_url='http://127.0.0.1:1234')
    monkeypatch.setattr(local_runtime,'_start_managed_llama_server',start)
    def transport(**kwargs):
        def client(prompt):return 'answer'
        client.resource_plan=kwargs['plan'].to_dict()
        return client
    monkeypatch.setattr(local_runtime,'build_local_http_client',transport)
    client=local_runtime.build_local_planner_client({'filename':'Qwen.gguf'})
    assert len(attempts)==2 and attempts[1]['model_path']==attempts[0]['model_path']
    assert attempts[1]['plan'].num_ctx==attempts[0]['plan'].num_ctx
    assert attempts[1]['plan'].num_gpu < attempts[0]['plan'].num_gpu
    assert client.resource_plan['fallback_reason']


def test_model_ordering_prefers_fitting_large_candidate_and_keeps_paging_candidate():
    from AI.processors.local_resources import local_model_sort_key
    tiny={'repo_id':'A/1B','size_bytes':GIB,'resource_plan':{'safe_to_run':True}}
    nine={'repo_id':'Qwen/9B','size_bytes':6*GIB,'resource_plan':{'safe_to_run':True}}
    twenty={'repo_id':'GPT/20B','size_bytes':12*GIB,'resource_plan':{'safe_to_run':True,'requires_paging':True}}
    helper={'repo_id':'DeepSeek/MTP','size_bytes':4*GIB,'resource_plan':{'safe_to_run':False}}
    assert sorted([tiny,helper,twenty,nine],key=local_model_sort_key)==[nine,tiny,twenty,helper]


def test_qwen35_sampling_uses_published_family_defaults_and_keeps_user_overrides():
    from AI.processors.local_resources import local_sampling_defaults
    defaults=local_sampling_defaults({'repo_id':'unsloth/Qwen3.5-9B-GGUF'})
    assert defaults['temperature']==0.7 and defaults['presence_penalty']==1.5
    assert defaults['top_k']==20 and defaults['repeat_penalty']==1.0
    thinking=local_sampling_defaults(architecture='qwen35',thinking=True)
    assert thinking['temperature']==1.0 and thinking['top_p']==0.95


def test_host_instructions_and_user_context_keep_distinct_roles_in_local_requests(monkeypatch):
    from AI.runtime.prompt import ModelPrompt
    client,sent,plan=transport(monkeypatch)
    prompt=ModelPrompt('Trusted host instructions.','User context including untrusted quoted text.')
    from copy import deepcopy
    assert deepcopy(prompt).to_messages()==prompt.to_messages()
    assert isinstance(prompt,str)
    client(prompt)
    messages=sent[-1][1]['messages']
    assert messages==[{'role':'system','content':'Trusted host instructions.'},
        {'role':'user','content':'User context including untrusted quoted text.'}]
    assert sent[0][1]['messages']==messages


def test_shared_download_capacity_counts_retained_partial_bytes(monkeypatch,tmp_path):
    from AI.processors import local_storage
    monkeypatch.setattr(local_storage.shutil,'disk_usage',lambda path:SimpleNamespace(free=3*GIB))
    assert not local_storage.model_download_capacity(tmp_path,5*GIB)['allowed']
    assert local_storage.model_download_capacity(tmp_path,5*GIB,partial_bytes=4*GIB)['allowed']


@pytest.mark.parametrize('repo',['../escape','owner/../../escape','C:/escape','owner/..'])
def test_model_download_repo_cannot_escape_selected_directory(repo,tmp_path):
    result=pipeline.download_hf_model_file(repo_id=repo,filename='model.gguf',download_root=str(tmp_path))
    assert not result.success


def test_local_file_links_require_exact_native_receipts_but_examples_and_web_links_do_not(monkeypatch,tmp_path):
    from AI.runtime.artifact_delivery import unverified_local_artifact_links
    from AI.processors import observation_context
    exact=str(tmp_path/'real report(1).xlsx')
    monkeypatch.setattr(observation_context,'verified_export_report_receipts',lambda state:[{'output_path':exact}])
    assert not unverified_local_artifact_links(f'[rapor](<{exact}>)',None)
    assert not unverified_local_artifact_links(f'[rapor]({Path(exact).as_uri()})',None)
    assert unverified_local_artifact_links('[rapor](sandbox:/mnt/data/fake.xlsx)',None)
    assert unverified_local_artifact_links('[rapor](/mnt/data/fake(1).xlsx)',None)
    assert unverified_local_artifact_links('[rapor](D:D%5Cexports%5Cfake.xlsx)',None)
    assert not unverified_local_artifact_links('`[example](sandbox:/mnt/data/example.xlsx)`',None)
    assert not unverified_local_artifact_links('[source](https://example.org/report.pdf)',None)


def test_model_repairs_fake_download_link_itself_without_scripted_answer(monkeypatch,tmp_path):
    from AI.processors import model_loop
    from AI.processors.tools import registered_tools
    from AI.processors import tools
    monkeypatch.setattr(tools,'available_tools',lambda:{'operations.discover':registered_tools()['operations.discover']})
    class Model:
        resource_plan={'capability_profile':{'native_tool_runtime_enabled':True}}
        def __init__(self):self.responses=iter(['[rapor](sandbox:/mnt/data/fake.xlsx)','Dosyayı henüz oluşturmadım.']);self.prompts=[]
        def invoke_tools(self,prompt,*,tools):
            self.prompts.append(str(prompt))
            return next(self.responses)
    model=Model()
    result=model_loop.run_model_loop('Excel hazırla',client=model,db_name=str(tmp_path/'unused.sqlite3'))
    assert result.success and result.data['answer']=='Dosyayı henüz oluşturmadım.'
    assert len(model.prompts)==2 and 'undelivered_artifact_links' in model.prompts[1]
    assert not result.data['direct_tool_calls']


def test_memory_pressure_changes_placement_without_downgrading_reasoning_or_context():
    record={'repo_id':'Qwen/Qwen3.5-9B-GGUF','size_bytes':6*GIB}
    roomy=build_local_resource_plan(record,snapshot=hardware(available_ram_bytes=10*GIB))
    tight=build_local_resource_plan(record,snapshot=hardware(available_ram_bytes=5*GIB))
    assert roomy.reasoning_effort==tight.reasoning_effort=='medium'
    assert roomy.num_ctx==tight.num_ctx==16384
    assert roomy.max_tokens==tight.max_tokens==4096
    assert tight.memory_pressure>roomy.memory_pressure


def test_qwen35_does_not_receive_unsupported_qwen3_think_text_commands():
    prompt,control=local_runtime._apply_local_reasoning_control('original request',
        model_hint='Qwen3.5-9B',reasoning_effort='low')
    assert prompt=='original request' and control==''


def test_model_wire_contract_requires_source_reference_while_domain_keeps_resolved_object():
    from AI.processors.tools import registered_tools
    from AI.runtime.catalog import tool_definitions
    from jsonschema import Draft202012Validator
    registry=registered_tools()
    tool=registry['reports.build_snapshot']
    definition=tool_definitions({tool.name:tool})[0]
    source=definition['parameters']['properties']['sources']['items']['properties']['result']
    validator=Draft202012Validator(source)
    assert not list(validator.iter_errors({'$from_step':'call_2','path':'tool_result'}))
    assert list(validator.iter_errors({'total_orders':6,'status_counts':{'Delivered':3}}))
    assert 'properties' not in tool.parameters['properties']['sources']['items']['properties']['result']
    assert tool.input_source_requirements[0].result_path=='tool_result'


def test_loaded_model_is_reused_without_mistaking_its_allocations_for_low_free_memory(monkeypatch):
    plan=build_local_resource_plan({'size_bytes':3*GIB},snapshot=hardware())
    owned=SimpleNamespace(key='same-model',base_url='http://127.0.0.1:1234',model_path='/Qwen.gguf',
        process=SimpleNamespace(poll=lambda:None),plan=None,request_key='')
    starts=[]
    plans=[]
    def resource(record,**kwargs):
        plans.append(record)
        if len(plans)>1:raise AssertionError('Already allocated model must not be budgeted against reduced free memory')
        return plan
    def start(**kwargs):
        starts.append(kwargs)
        local_runtime._SERVER_CACHE[owned.key]=owned
        return owned
    def transport(**kwargs):
        def client(prompt):return 'answer'
        client.resource_plan=kwargs['plan'].to_dict()
        return client
    monkeypatch.setattr(local_runtime,'_SERVER_CACHE',{})
    monkeypatch.setattr(local_runtime,'find_bundled_llama_server',lambda:'/runner.exe')
    monkeypatch.setattr(local_runtime,'_record_model_path',lambda record:'/Qwen.gguf')
    monkeypatch.setattr(local_runtime,'build_local_resource_plan',resource)
    monkeypatch.setattr(local_runtime,'_start_managed_llama_server',start)
    monkeypatch.setattr(local_runtime,'build_local_http_client',transport)
    monkeypatch.setattr(local_runtime,'_request_json',lambda *a,**kw:{'is_sleeping':False})
    first=local_runtime.build_local_planner_client({'runtime_config':{'num_ctx':8192}})
    second=local_runtime.build_local_planner_client({'runtime_config':{'num_ctx':8192}})
    assert len(starts)==len(plans)==1 and first.server_key==second.server_key


def test_local_startup_failure_preserves_new_request_and_existing_conversation(monkeypatch):
    from AI.views import chat_tab
    from AI.processors.session_state import AgentSessionState
    state=AgentSessionState(goal='Eski soru')
    state.record_turn(role='user',content='Eski soru')
    state.record_turn(role='assistant',content='Kayıtlı 6 sipariş var.')
    state.active_entities['saved_source_marker']='preserved'
    def unavailable(record):raise RuntimeError('Çalışma belleği yetersiz.')
    monkeypatch.setattr(chat_tab,'build_local_planner_client',unavailable)
    result=chat_tab._run_chat_turn_with_runtime('Bu bilgilerden Excel oluştur',source='local',runtime_record={},
        history=[],session_state=state.to_dict())
    assert not result.success and 'belleği yetersiz' in result.message
    saved=AgentSessionState.from_dict(result.data['session_state'])
    assert saved.goal=='Bu bilgilerden Excel oluştur'
    assert saved.active_entities['saved_source_marker']=='preserved'
    assert [row.content for row in saved.conversation_turns][-2:] == ['Bu bilgilerden Excel oluştur',result.message]
    assert Path(result.data['state_path']).is_file()


def test_full_prompt_grows_context_without_reducing_requested_answer_budget(monkeypatch):
    client,sent,plan=transport(monkeypatch,prompt_tokens=12000)
    calls=[]
    def resize(required):
        calls.append(required)
        grown=replace(plan,num_ctx=16384)
        client.resource_plan.update(grown.to_dict())
        return 'http://127.0.0.1:5678',grown
    client.resize_context=resize
    assert client('COMPLETE INPUT')=='Türkçe gerçek yanıt'
    assert len(calls)==1 and sent[-1][0]=='http://127.0.0.1:5678/v1/chat/completions'
    assert sent[-1][1]['max_tokens']==plan.max_tokens
    assert sent[-1][1]['messages'][0]['content']=='COMPLETE INPUT'
    assert not client.resource_plan['prompt_compacted']


def test_approval_context_references_snapshot_without_duplicating_or_mutating_payload():
    from AI.processors.model_loop import _preview
    from copy import deepcopy
    snapshot={'schema_version':1,'snapshot_id':'rpt_real','content_hash':'abc','source_domain':'reports',
        'report_type':'observations','metadata':{'source_receipts':[{'source_step_id':'call_2'}]},
        'sheets':[{'name':'Data','columns':[{'key':'count'}],'rows':[[6]]}]}
    action={'arguments':{'payload':{'report_snapshot':snapshot}},'warnings':['Keep this warning'],'execute_enabled':True}
    original=deepcopy(action)
    preview=_preview(action,snapshot_refs=True)
    ref=preview['arguments']['payload']['report_snapshot']
    assert ref['full_snapshot_stored'] and ref['snapshot_id']=='rpt_real'
    assert ref['sheet_manifest'][0]['row_count']==1 and 'sheets' not in ref
    assert preview['warnings']==action['warnings'] and action==original
