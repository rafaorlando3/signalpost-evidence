# Search cost comparison — checked 23 October 2026

No payment or paid fallback is authorized. The R5 local measurement uses the existing Tavily Researcher free plan only, after account and remaining-credit checks. Pay-as-you-go and automatic upgrade were visibly off; the service states that requests stop at the plan limit. A configured command cap is a limit, not proof of an unused monthly balance.

## Comparable units

1,000 companies/day, one ordinary query/company, for 30 days means 30,000 queries. Three queries/company means 90,000. Prices below exclude tax, extra result pages, extraction, model calls and negotiated discounts. Discovery quality and exact-entity verification have not been compared across these providers. These are published prices, not a licensing approval or a purchased service.

| Provider | Published price / 1,000 searches | 30k / 90k queries, before free credits | Initial cash / relevant condition |
|---|---:|---:|---|
| DataForSEO Normal | US$0.60 | US$18 / US$54 | US$50 minimum top-up; queued, average 5 minutes |
| Serper Starter | US$1.00 | US$30 / US$90 consumed | US$50 buys 50k; 6-month validity; generally 1–2s |
| DataForSEO Priority | US$1.20 | US$36 / US$108 | US$50 minimum; about 1 minute average |
| DataForSEO Live | US$2.00 | US$60 / US$180 | US$50 minimum; typically under 6 s |
| Mojeek Startup | GBP2 | GBP60 / GBP180 | Restrictive temporary-cache terms |
| Exa Lite | US$4.00 | US$120 / US$360 | US$10 monthly credit plus onboarding credit; verify account |
| Brave Search | US$5.00 | US$150 / US$450 | US$5 monthly credit; payment details required |
| You.com Search | US$5.00 | US$150 / US$450 | Canonical page says US$10 initial credit; free MCP 100/day |
| Tavily basic PAYG | US$8.00 | US$240 / US$720 | 1,000 monthly free credits; no card for Researcher |
| SerpAPI | Monthly plans | US$275/30k / US$725/100k | 250 monthly free requests; plan-dependent |
| Kagi Search API | US$12.00 | US$360 / US$1,080 | Separate from personal subscription |

Tavily subscription plans may cost less than its PAYG rate (e.g. US$220/38k or US$500/100k). They are not activated. Google Custom Search is closed to new customers and scheduled to end 1 January 2027 for existing customers; it is not a new integration option. SearXNG software is free but has no universal free upstream capacity, rights or reliability guarantee.

## Conditions that affect the real price

- DataForSEO Normal is the lowest nominal price in this comparison, but its published queue latency does not fit this collector’s 90-second local company budget. Operators such as site:, intitle: or inurl: can multiply its base tariff by 5. Do not price the current exclusion-heavy queries at the ordinary rate.
- Serper is the lowest published fast option at these volumes. Its advertised US$0.30/1k tier requires US$3,750 upfront, which does not minimize this project’s cash outlay. Two US$50 Starter purchases for 90k is an estimate from the published package, not a verified checkout. The initial 2,500-query trial is not a recurring allowance.
- Exa Lite monthly credit could cover 2,500 ordinary queries at the published US$4/1k rate, subject to account terms and additional content charges. No account balance was presumed or account created.
- You.com pages conflict on the signup bonus (US$100 vs canonicalUS$10). Do not budget againstUS$100. The 100/day MCP route does not sustain 1,000 companies/day.
- Tavily basic is 1 credit/query; advanced is 2. R5 fixes basic, auto_parameters=false and includes usage. A 100-company local pilot with at most 3 queries/company is capped at 300 credits. Failed attempts retain reservations; unknown consumption halts further searches. Separate runs share the monthly account balance, not a reset allowance.
- Monthly credits are not daily credits. After free allowance, R5 makes no paid fallback. API-account billing is not inferred from request counts or an absent usage field.

## Rights and reproducibility

Serper, DataForSEO and SerpAPI are not official Google APIs. Their availability does not demonstrate that a particular collection method is permitted in Signalpost. Their contracts and upstream rights need review before use. Mojeek Startup limits cache to about 1hour for the same user; Kagi restricts persistent caching/benchmark datasets. Do not substitute either for an audit replay cache without a suitable licence. Storage rights are not a universal licence to republish third-party pages.

R5 uses search responses only to discover URLs. It retains only candidate URLs, legal/contact URL hints and retrieval metadata, not search snippets, answers, keys or complete provider responses. Claims require independent retrieval from a permitted source and exact legal-entity attribution. Third-party pages retain their own rights.

## Primary sources

- DataForSEO pricing: https://dataforseo.com/pricing/google-serp/google-organic-serp-api
- Latency: https://dataforseo.com/help-center/fastest-method-to-get-results
- Operators: https://dataforseo.com/help-center/serp-api-cost-explained
- Minimum top-up: https://dataforseo.com/faq
- Serper price/FAQ: https://serper.dev/ ; terms: https://serper.dev/terms
- Exa pricing: https://exa.ai/docs/admin/pricing ; billing: https://exa.ai/docs/admin/billing
- Brave pricing: https://api-dashboard.search.brave.com/documentation/pricing
- Tavily credits: https://docs.tavily.com/documentation/api-credits
- Tavily account usage: https://docs.tavily.com/documentation/api-reference/endpoint/usage
- You.com current pricing: https://you.com/pricing
- Mojeek: https://www.mojeek.com/services/search/web-search-api/ ; terms: https://www.mojeek.com/about/legal/api-terms.html
- Kagi: https://kagi.com/api/pricing ; terms: https://kagi.com/privacy/api
- SerpAPI: https://serpapi.com/pricing
- Google: https://developers.google.com/custom-search/v1/overview
- Signalpost source policy: https://www.builderr.ai/starter-briefs/signalpost-sources.md
