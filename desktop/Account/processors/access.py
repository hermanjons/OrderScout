"""Local data access and configured marketplace transport are distinct capabilities."""
from __future__ import annotations

from collections.abc import Mapping

from Account.processors.environment import account_environment_scope
from Feedback.processors.pipeline import Result
from settings import DB_NAME


def account_access_profile(account):
    def value(name, default=None):
        return account.get(name, default) if isinstance(account, Mapping) else getattr(account, name, default)

    scope=account_environment_scope(account)
    local=scope['environment']=='local'
    blockers=[]
    if local:
        blockers.append('local_data_account')
    elif str(value('platform','')).upper()!='TRENDYOL':
        blockers.append('marketplace_transport_not_supported')
    else:
        # This adapter only validates configuration; it performs no request and
        # resolves no secrets. Credential references remain in their owner.
        from Marketplaces.api.trendyol.base_api import trendyol_account_client_kwargs
        try:
            trendyol_account_client_kwargs(account)
        except (ValueError, TypeError):
            blockers.append('marketplace_configuration_incomplete')
    if not value('is_active',True):
        blockers.append('inactive_account')
    return {**scope, 'local_database_access':True,
            'marketplace_credentials_required_for_local_data':False,
            'remote_access_configured':not blockers,
            'remote_access_blockers':blockers,
            'remote_connection_applicable':not local,
            'remote_connection_verified':False}


def validate_remote_account_access(*, api_account_ids, db_name=DB_NAME):
    """Fail before any approval/network operation for an unavailable transport."""
    from Account.processors.agentic_repository import list_accounts

    ids=list(dict.fromkeys(int(value) for value in api_account_ids))
    result=list_accounts(pks=ids,db_name=db_name)
    if not result.success:
        return result
    accounts={int(row.pk):row for row in (result.data or {}).get('records',[])}
    missing=sorted(set(ids)-set(accounts))
    profiles=[{'api_account_id':pk,'store_name':accounts[pk].comp_name,
               **account_access_profile(accounts[pk])} for pk in ids if pk in accounts]
    valid=bool(ids) and not missing and all(p['remote_access_configured'] for p in profiles)
    data={'valid':valid,'api_account_ids':ids,'missing_account_ids':missing,'accounts':profiles,
          'local_database_access':True,'marketplace_credentials_required_for_local_data':False,
          'network_request_performed':False,'db_write_performed':False}
    if not valid:
        return Result.fail('Seçilen hesaplarda pazaryeri API senkronizasyonu yapılandırılmamış. '
                           'Yerel kayıtları okuma, hesaplama ve dosya oluşturma API bağlantısı gerektirmez.',
                           close_dialog=False,data={**data,'code':'remote_access_unavailable'})
    return Result.ok('Pazaryeri bağlantı yapılandırması mevcut; canlı erişim doğrulanmadı.',
                     close_dialog=False,data=data)
