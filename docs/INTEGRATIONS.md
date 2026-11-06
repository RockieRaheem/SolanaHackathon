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

## Stellar

The settlement layer must treat on-ramp, on-chain transfer and off-ramp as separate states. Production requires a validated Uganda-compatible provider corridor and compliance review.
