# Labels Goals

Updated: 2026-07-15

Parent contracts: `../../Core/docs/domain_goals_contract.md`,
`../../AI/docs/goals.md`

Parity evidence: `../../AI/docs/labels_agentic_parity_matrix.md`

## Ürün Sonucu ve Sahiplik

Labels; doğrulanmış Orders selection'ından label payload üretme, sıralama, DOCX export,
belge içeriği doğrulama ve ilgili extracted/receipt state'ini güncellemenin sahibidir.
Sipariş kapsamını Labels yeniden seçmez; Orders structured selection'ını tüketir.

## Capability Sözleşmesi

```text
read: 0
write: 2
total: 2
```

## Agentic Kabul

- `N` selected order → `N` prepare record ref → `N` DOCX içeriği → `N` verify/audit
  invariant'ı korunur.
- Prepare ile execute ayrıdır. Kullanıcı yalnız hazırlama ister veya yazdırmayı
  yasaklarsa approval/execute yan etkisi oluşmaz.
- Stale/superseded approval çalıştırılamaz; kullanıcı kapsam düzeltirse yeni fingerprint
  ve yeni kart üretilir.
- DOCX verify yalnız dosya varlığına değil, onaylanan order number içeriğine bakar.

## Risk

Label prepare salt güvenli; file export ve local extracted marker R1'dir. Manuel kritik
workflow, gerçek kaynak verili DOCX read-back ve Orders task continuation
`verified_baseline`dır. Yeni template/formatlar aynı content verify sözleşmesine uyar.

## Güncel Durum

- Orders→Labels exact selection zinciri: `verified_baseline`
- Local file/DB execute/verify/audit: `verified_baseline`
- Gemini/OpenRouter/local Orders yeniden kabulü: `verified_baseline`
- Bağımsız Labels domain task kataloğu: `not_applicable` — görev Orders selection
  bağlamında yürür; ayrı katalog aynı işi çoğaltmamalıdır
