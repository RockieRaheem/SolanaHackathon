# Integration Notes

## Payment rails

Provider adapters should normalise external transactions into the internal Payment model while preserving the original provider payload/reference.

Potential adapters:
- SchoolPay
- Bank feeds/statements
- Mobile Money / payment aggregator
- Card payment provider
- Cash entry workflow

## Messaging

Africa's Talking can be the first SMS and later USSD implementation, but the application should call a MessagingProvider interface rather than hard-code one vendor.

## Local language

Sunbird AI can be implemented behind a LanguageService interface. Translation failure must never stop registration, payment or settlement workflows.

## Solana

The hackathon rail uses Solana devnet and a school-owned Wallet Standard destination. The ledger must treat wallet transfer, school verification, UGX allocation, and any future off-ramp as separate states. Production requires an audited programme, a validated Uganda-compatible provider corridor, live pricing, RPC confirmation, and compliance review.
