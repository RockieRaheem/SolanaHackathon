# SomaFund Solana Hackathon Build

## Product decision

SomaFund is HarambeeOne's collaborative school-fee funding rail. A school turns a verified learner obligation into a privacy-safe public campaign. Parents, relatives, diaspora family, employers, and sponsors can contribute small amounts toward that obligation. The school remains the financial authority and allocates only verified contributions to the learner's UGX ledger.

This is a strong Solana fit because the contribution is global, wallet-authorised, inexpensive enough for small contributors, independently verifiable, and separated from sensitive learner data.

## Hackathon track alignment

The primary submission is the **DeFi track**: coordinated funding of a real-world education obligation through a transparent payment rail. The project should also be submitted for **Top 3 Overall** because it combines an existing school-finance system, a Uganda-specific problem, privacy controls, and a working on-chain flow.

Use the **Best Beginner Hack** category only if the participant or team meets the organiser's beginner definition. Claim the **AI track** only if the demo actually shows the optional, consented Gemma review; AI is not needed to make the Solana contribution credible.

## Implemented vertical slice

1. A bursar creates an anonymous campaign backed by an existing learner obligation.
2. The school configures and verifies its Solana devnet address.
3. A donor opens the public campaign without seeing learner identity.
4. The donor connects a Wallet Standard wallet.
5. The app converts the entered UGX pledge using a clearly labelled fixed hackathon quote.
6. The donor authorises a real devnet SOL transfer directly to the verified school address.
7. HarambeeOne records the transaction signature as the pledge's external reference.
8. The bursar verifies the pledge.
9. Payment, allocation, learner-ledger credit, receipt evidence, settlement evidence, and audit event post together.

## Architecture and trust boundaries

    Donor wallet
        |
        | signs devnet SOL transfer
        v
    Verified school wallet <------> Solana devnet / Explorer
                                          |
                                          | public transaction signature only
                                          v
    Next.js donor portal -> FastAPI controls -> Supabase PostgreSQL
                                                 |
                                                 +-- private learner obligation
                                                 +-- exact UGX ledger
                                                 +-- tenant isolation
                                                 +-- audit evidence

Solana stores the public value movement. Supabase stores learner identity, consent, the school invoice, the UGX accounting record, and audit history. No learner name, phone number, admission number, school identifier, or invoice detail belongs on-chain.

## Honest MVP boundary

The hackathon implementation is a **direct-to-school devnet payment rail**. It is not yet a custodial escrow and must not be presented as one. “Vault” describes the collaborative product experience, while the current custody model sends value to a school-owned wallet.

Before mainnet, replace the direct transfer with an audited Solana programme using programme-derived vault accounts and explicit release/refund rules. Also add a licensed UGX on/off-ramp, live price quotes with expiry and slippage controls, signature/amount/destination verification through a trusted RPC, confirmations and retry handling, wallet ownership proof, monitoring, and Ugandan legal/privacy review.

## Demo script

1. Sign in as a school owner or bursar.
2. Open **Manage campaigns** and show that the campaign target comes from a real obligation.
3. Add a **Solana devnet wallet** destination owned by the institution.
4. Open the campaign's public link in another browser profile.
5. Connect Phantom, Solflare, or another Wallet Standard wallet configured for devnet.
6. Enter a small UGX pledge and approve the displayed SOL amount.
7. Open the returned signature in Solana Explorer.
8. Return to the bursar portal and verify the pledge.
9. Show the learner ledger, receipt reference, and audit evidence.
10. State the privacy and mainnet limitations before finishing.

## Judging message

> HarambeeOne already knows what a learner genuinely owes. SomaFund lets a family or community fund that verified invoice together, from anywhere, while Solana provides fast public payment proof and HarambeeOne protects the child's identity and keeps the school's UGX books correct.

## Completion gates for the weekend

- Real devnet transfer succeeds from a supported wallet.
- Only institution-verified Solana destinations appear publicly.
- The signature is retained even if backend pledge recording fails.
- Duplicate pledge submission is idempotent.
- A pending pledge cannot change a learner balance.
- Bursar verification atomically posts allocation, ledger, receipt evidence, settlement evidence, and audit.
- No learner PII appears in transaction data or public APIs.
- Mainnet remains disabled.
- Focused backend tests, web lint, and production build pass.