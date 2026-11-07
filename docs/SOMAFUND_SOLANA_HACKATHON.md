# SomaFund Solana Hackathon Build

## Product decision

SomaFund is HarambeeOne's collaborative school-fee funding rail. A school turns a verified learner obligation into a privacy-safe public campaign. Parents, relatives, diaspora family, employers, and sponsors contribute small amounts directly to the institution's verified Solana wallet, while HarambeeOne automatically credits only a cryptographically verified payment to the learner's private UGX account.

This is a strong Solana fit because contributions can be global, wallet-authorized, fast, inexpensive, independently verifiable, and separated from sensitive learner data.

## Hackathon track alignment

The primary submission is the **DeFi track**: coordinated funding of a real-world education obligation through a transparent payment rail. The project should also be submitted for **Top 3 Overall** because it combines an existing school-finance system, a Uganda-specific problem, privacy controls, and a working on-chain flow.

Use **Best Beginner Hack** only if the participant meets the organizer's definition. Claim the **AI track** only if the demo shows the separate, optional and consented Gemma review; AI is not required for credible Solana settlement.

## Implemented vertical slice

1. A bursar publishes an anonymous campaign backed by an existing learner obligation.
2. The institution configures and verifies its Solana devnet wallet.
3. A donor opens the public campaign without seeing learner identity and connects a Wallet Standard wallet.
4. The server creates an idempotent, expiring checkout containing the exact recipient, integer lamports, fixed judging quote, cluster and anonymous campaign memo.
5. The wallet signs one atomic transaction containing the System Program transfer and the checkout memo.
6. The server independently queries Solana RPC and requires a successful `confirmed` or `finalized` transaction.
7. Verification checks the signer, exact recipient, exact lamports, exact memo, transaction time and unused signature.
8. A valid transaction atomically posts the payment, learner allocation, ledger credit, sequential receipt, Solana signature and confirmation slot, audit event and notifications.
9. Confirmation retries return the same receipt; a signature cannot fund another checkout; an unconfirmed Solana pledge cannot be manually approved.
10. If the browser loses connectivity after wallet approval, the donor retains the signature and can retry server confirmation safely.

## Architecture and trust boundaries

    Donor wallet
        |
        | atomic devnet SOL transfer + anonymous checkout memo
        v
    Verified school wallet <------> Solana RPC / Explorer
                                          |
                                          | server verifies transaction evidence
                                          v
    Next.js donor portal -> FastAPI controls -> Supabase PostgreSQL
                                                 |
                                                 +-- private learner obligation
                                                 +-- exact UGX ledger and receipt
                                                 +-- signature replay protection
                                                 +-- tenant isolation and audit evidence

Solana stores public value movement and an anonymous campaign reference. Supabase stores learner identity, consent, school invoice, exchange-rate snapshot, UGX accounting, receipt, confirmation evidence and audit history. Learner name, phone, admission number and invoice details never go on-chain.

## Honest MVP boundary

This is a **direct-to-school devnet payment rail**, not custodial escrow. “Vault” describes collaborative funding; the current custody model sends value directly to a school-owned wallet. Devnet SOL has no monetary value, and the fixed UGX/SOL quote exists only for a deterministic hackathon demo.

Before mainnet, use a dedicated production RPC provider, licensed UGX on/off-ramp, live signed quotes with expiry and slippage controls, operational monitoring, wallet-ownership ceremony, independent security review, and Ugandan payments/privacy/legal review. A true conditional vault would additionally require an audited Solana program with program-derived accounts and explicit release/refund rules.

## Demo script

1. Sign in as owner or bursar, publish an obligation-backed campaign, and verify a Solana devnet destination.
2. Open its public link in another browser profile and connect a devnet Wallet Standard wallet.
3. Enter a small whole-UGX contribution and approve the exact SOL transaction.
4. Show its transfer and `HARAMBEEONE:HSP-...` memo in Solana Explorer.
5. Return to SomaFund and show automatic confirmation, receipt number and confirmation slot—there is no manual bursar approval.
6. Show the learner ledger credit and settlement evidence in the school workspace.
7. Retry confirmation to demonstrate idempotency, then explain that learner identity stayed off-chain.
8. State the direct-payment, fixed-quote and devnet limitations.

## Judging message

> HarambeeOne already knows what a learner genuinely owes. SomaFund lets family and community fund that verified invoice together from anywhere. Solana supplies fast public payment proof; HarambeeOne verifies every on-chain detail, protects the child’s identity, and keeps the school’s UGX books correct.

## Verified completion evidence

- Exact server-created checkout prevents browser-controlled recipient, amount or memo changes.
- Solana RPC verification requires successful confirmed/finalized evidence and the expected signer, recipient, lamports and memo.
- Transaction signatures are globally unique and confirmed evidence becomes database-immutable.
- Confirmation and checkout retries are idempotent; manual approval cannot bypass chain verification.
- Payment, allocation, ledger, receipt, settlement anchor, audit and notification records commit together.
- Focused Ruff checks pass and all 18 support workflow tests plus 6 direct Solana RPC evidence tests pass, including automatic settlement, retry, replay and bypass controls.
- Live Supabase is at Alembic head `c7e5a1d9f204`; the verification script passed RLS, revoked Data API grants, signature uniqueness and the immutable-evidence trigger.
- The Solana UI compiles and type-checks in the production Next.js build.
