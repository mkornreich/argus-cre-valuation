# What was argussoftware.com — and what happened to it?

*Analysis compiled 2026-10-24 from live DNS/HTTP probes, Internet Archive (Wayback Machine) captures, domain registration (RDAP) records, and public reporting.*

## TL;DR

`argussoftware.com` was the home of **ARGUS**, for decades the de‑facto industry‑standard
software for **commercial‑real‑estate (CRE) financial modeling, discounted‑cash‑flow (DCF)
valuation, and asset/portfolio management**. The company behind it (ARGUS Financial Software →
Realm Business Solutions → ARGUS Software, Inc., headquartered in Houston, Texas) was **acquired
by the Canadian firm Altus Group in 2011 for US$130 million**.

The company didn't fail or disappear — it was **absorbed**. Altus kept ARGUS as a product brand
(ARGUS Enterprise, ARGUS Developer, and today **ARGUS Intelligence**) but **retired the standalone
website**: around 2018–2019 `argussoftware.com` began permanently redirecting to
`argus.altusgroup.com`, and later to `altusgroup.com/argus/`. The domain is still owned and renewed
(through 2027) but **no longer serves a website** — it exists today only as a Microsoft‑365 email
endpoint, likely kept for brand protection and legacy addresses. The ARGUS products live on under
Altus Group (TSX: AIF), which itself was exploring a possible sale as of 2025.

---

## 1. What the site / company was

ARGUS began in the 1980s as a **discounted‑cash‑flow valuation tool for commercial real estate**,
built by a Houston‑based company that became known as **ARGUS Financial Software, Inc.** Archived
copies of the homepage capture how it positioned itself:

- **1998 homepage:** *"ARGUS Financial Software — ARGUS Lease by Lease Version 7 — The Industry
  Standard Tool for Analysis, Valuations, Due Diligence, Asset Management & Budgeting."* It
  advertised "Largest Overall Market Share" and "Highest Customer Loyalty," and listed products
  including ARGUS and ARGUS Development & Unit Sales. Contact addresses were
  `argus@argussoftware.com`, `argussales@…`, `argussupport@…`, and it called itself the "ARGUS
  Financial Software World Headquarters."
- **2009 homepage:** rebranded as **"ARGUS Software, Inc."** (© 2009), a Flash‑driven site.
- **2017 homepage:** *"ARGUS Software | Software Solutions for Commercial Real Estate Analysis,
  Valuation, Asset and Portfolio Management and Development Feasibility."*

**What it actually did:** ARGUS let analysts, appraisers, lenders, REITs, brokers, and asset
managers model a property's cash flows lease‑by‑lease and compute its value via DCF — the standard
underwriting and valuation workflow in institutional CRE. Over time the product family grew to
include **ARGUS DCF / Enterprise** (valuation & asset management) and **ARGUS Developer** (UK‑origin
development‑feasibility software).

Notable early milestone: in mid‑**1999**, Houston‑based ARGUS Financial Software acquired the assets
of Clearwater, FL‑based **DYNA Software & Consulting**, absorbing DYNA's equity/development/REIT
analysis product line.

---

## 2. Corporate timeline — how the company changed hands

| Period | What happened |
|---|---|
| 1980s–1990s | ARGUS created as a CRE DCF valuation tool; **ARGUS Financial Software, Inc.** operates from Houston, TX. Domain `argussoftware.com` registered **March 5, 1996**. |
| 1999 | ARGUS acquires the assets of **DYNA Software & Consulting**. |
| 2000s | Consolidation with UK CRE‑software lineage (the "Circle"/Developer products); the group becomes **Realm Business Solutions**, later renamed **ARGUS Software, Inc.** Private‑equity owners **Lightyear Capital** and **Insight Venture Partners** hold the company. |
| April 2011 | **Altus Group Limited (Canada, TSX: AIF)** agrees to acquire ARGUS Software for **US$130 million** (reported as ~$80M cash + ~$50M convertible debentures). This marked Altus's entry into the CRE‑software business. (Some sources date the close to June 2011.) |
| 2012 onward | Altus makes **ARGUS Enterprise (AE)** the flagship; ARGUS operates as an Altus brand/subsidiary. |
| Dec 2015 | Altus bolts on **Integrated Real Estate Resources** to extend ARGUS's application services. |
| ~2018–2019 | **Standalone website retired.** `argussoftware.com` begins permanently (HTTP 301) redirecting into **`argus.altusgroup.com`**, folding the brand into Altus's own domain. |
| 2020s | ARGUS sold under Altus's analytics segment; Altus begins transitioning customers to a rebranded/upgraded **ARGUS Intelligence** platform (with ARGUS Enterprise still a major revenue line). |
| 2024 | Altus sells its (separate) **property‑tax business to Ryan** for ~C$700M — *not* ARGUS. |
| 2025 | Altus Group confirms a **strategic review / potential sale** of the company after inbound acquisition interest. Outcome not confirmed as of this writing. |

---

## 3. Technical evidence — the state of argussoftware.com today

This is the "what happened to them" part, shown directly from the domain and the archive.

**The live domain no longer hosts a website.**
- `www.argussoftware.com` does **not resolve** (DNS `SERVFAIL`) — the web host record is gone.
- The apex `argussoftware.com` resolves only to **Microsoft‑365 / Outlook infrastructure**
  (IPs in Microsoft's `52.96.x` / `40.99.x` ranges; `2603:1036:…` IPv6; MX =
  `argussoftware-com.mail.protection.outlook.com`). An HTTP request to the apex returns a generic
  Microsoft `301` from `Microsoft-HTTPAPI/2.0` and no real site content.
- **Interpretation:** the domain is retained for **email only** (and brand protection), not for a
  public website.

**Registration (RDAP) shows it's deliberately kept alive, not abandoned.**
- Created: **1996‑03‑05** · Expires: **2027‑03‑06** · Last changed: **2026‑05‑15**
- Registrar today: **Amazon Registrar, Inc.** (i.e., managed via AWS, consistent with a large
  corporate owner keeping the asset renewed).

**Wayback Machine capture history tells the migration story:**

| Years captured | HTTP status | Meaning |
|---|---|---|
| 1996 – 2009 | `200` | Live, standalone ARGUS Financial Software / ARGUS Software site. |
| 2010 – 2014 | `302` | Temporary redirects to an internal `/en/` path (transition era around the Altus acquisition). |
| 2015 – 2018 | `200` | Live again — ARGUS Software site under Altus ownership. |
| 2019 – 2024 | `301` | **Permanent** redirects **off the domain**: → `argus.altusgroup.com` (2019–~2021), then → `www.altusgroup.com/argus/` (by 2024). |

The last Wayback capture in this yearly sample is 2024‑01‑01, already a permanent redirect to
`altusgroup.com/argus/`.

**Conclusion from the evidence:** the brand and its website were intentionally **merged into
Altus Group's own web presence**, and the original domain was demoted to an email‑only placeholder.

---

## 4. So — what happened to them?

They were **acquired and brand‑consolidated, not shut down.**

1. ARGUS was the dominant CRE valuation/DCF software for ~25+ years, run by a Houston company that
   passed through private‑equity ownership (Lightyear Capital / Insight Venture Partners).
2. **Altus Group bought it in 2011 for US$130M.**
3. Altus kept the valuable **ARGUS** brand on its products (Enterprise, Developer, now ARGUS
   Intelligence) but **shut down the independent `argussoftware.com` website**, redirecting it into
   `altusgroup.com`.
4. The **ARGUS software still exists and is actively sold today** — as an Altus Group product line.
   Altus itself remains a public company and was exploring a potential sale/merger as of 2025.

In short: the **website** died (circa 2018–2019, by redirect); the **company** was absorbed into
Altus Group (2011); the **product** is alive and well.

---

## 5. Open questions / caveats

- **Exact founding year & founder:** secondary sources date the DCF tool to **1985** and name
  **Lori Paluska** as founder, but this is only single‑sourced and unverified here.
- **Acquisition close date:** reported as **April 2011** (announcement) vs **June 2011** (close);
  value consistently **US$130M**, with minor variation in cash/debenture split.
- **Corporate lineage** (ARGUS Financial Software ↔ Realm Business Solutions ↔ "Circle"/Developer UK
  side) is reported slightly differently across sources; the broad arc (Houston CRE software →
  Realm/ARGUS Software, Inc. → Altus) is consistent.
- **Current Altus status/CEO and any 2025–2026 sale outcome** were not fully resolved from available
  reporting; confirm against Altus Group investor relations for anything time‑sensitive.

---

## Sources

Primary evidence gathered directly for this analysis:
- Live DNS / HTTP probes of `argussoftware.com` and `www.argussoftware.com` (2026‑10‑24).
- Domain registration via RDAP (Verisign `.com` registry): created 1996‑03‑05, expires 2027‑03‑06.
- Internet Archive Wayback Machine CDX capture index and archived homepages
  (1998, 2009, 2017 snapshots; redirect targets for 2010/2014/2019/2021/2024).

Public reporting / references:
- [Altus Group — Wikipedia](https://en.wikipedia.org/wiki/Altus_Group)
- [Willkie Farr — "Willkie Advises Realm Solutions in its Sale to Altus Group" ($130M, Apr 12 2011)](https://www.willkie.com/news/2011/04/willkie-advises-realm-solutions-in-its-sale-to-a__)
- [Law360 — "Goodmans, Hodgson Rep Altus In $130M Software Buy"](https://law360.com/articles/238405/goodmans-hodgson-rep-altus-in-130m-software-buy)
- [Private Equity Wire — "Lightyear Capital sells ARGUS Software to Altus Group"](https://www.privateequitywire.co.uk/lightyear-capital-sells-argus-software-altus-group/)
- [GlobeNewswire — "Altus Group Enhances ARGUS Software Through Acquisition of Integrated Real Estate Resources" (Dec 2015)](https://www.globenewswire.com/news-release/2015/12/01/1092248/0/en/Altus-Group-Enhances-ARGUS-Software-Through-Acquisition-of-Integrated-Real-Estate-Resources.html)
- [WealthManagement.com — "ARGUS Financial Software snaps up DYNA" (1999)](https://www.wealthmanagement.com/news/argus-financial-software-snaps-dyna)
- [PitchBook — ARGUS Software overview](https://pitchbook.com/profiles/company/10267-03)
- [CB Insights — ARGUS Software](https://www.cbinsights.com/company/argus-software)
- [Preqin — ARGUS Software profile](https://www.preqin.com/data/profile/asset/argus-software/40813)
- [Altus Group — ARGUS Enterprise / JLL cloud transition press release](https://www.altusgroup.com/press-releases/altus-group-and-jll-begin-transition-to-cloud-enabled-argus-enterprise)
- [Bisnow — "Altus Group, Maker Of Popular CRE Finance Software Argus, Confirms It Is For Sale"](https://www.bisnow.com/news/national/commercial-real-estate/altus-group-maker-of-widely-used-cre-finance-software-confirms-its-up-for-sale-130548)
- [CREtech — "Altus Group, Creator of ARGUS CRE Software, Considers Strategic Sale"](https://www.cretech.com/?p=69147)
