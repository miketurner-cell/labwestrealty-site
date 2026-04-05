# Lab West Realty Site — Project Memory

## Project
Static HTML recruiting website for Royal LePage Turner Realty — Labrador West office.
Domain: labwestrealty.com
Purpose: Recruit licensed REALTORS® for Labrador City / Wabush office.
Owner: Mike Turner (miketurner@royallepage.ca)

## Process Rules (MANDATORY)
1. **ALWAYS screenshot after any visual change** — never skip this step
2. **Run `python3 tools/pre-deploy-check.py` before every deploy** — fix all errors first
3. **Use `tools/page-template.html` for new pages** — replace `xx` prefix and placeholders
4. **Never fabricate names, URLs, testimonials, or data** — verify everything against real sources
5. **Dark theme only** — Lab West uses #0a0a0a backgrounds like Gander (not light theme like Goose Bay)

## Design System — Dark Theme
Lab West uses the dark theme design system from Gander:

### Dark Theme Tokens
- **Backgrounds**: #0a0a0a (darkest), #111111 (cards/sections), #1a1a1a (alt dark)
- **Text**: #fff (headings), rgba(255,255,255,0.7) (body), #bbb (secondary), #ddd (hero sub)
- **Accent**: #EA002A (red), #c8001f (hover red)
- **Borders**: #222 (cards), #1e1e1e (subtle)
- **Cards**: background #111111, border 1px solid #222, border-radius 8px
- **Fonts**: Raleway 800/900 headings, Roboto 300/400 body
- **H2 standard**: clamp(26px, 4vw, 38px)
- **Nav height**: 80px
- **Red pill phone button**: #EA002A bg, 30px border-radius

### Dark Theme — DO NOT
- Never use #0a0a0a, #111, #1a1a1a, #222, #333, #888 as text colors on dark backgrounds
- Never use white backgrounds for cards — all cards use #111111 with #222 border

## Nav Structure (Critical)
Single-page recruiting site, so nav uses simple anchor links:
- Brand: "Turner Realty" with "Royal LePage" subtitle
- Links: Why Join Us (#why-join), Our Track Record (#track-record), What We Offer (#what-we-offer), Contact (#contact)
- Phone pill: 709-256-7999, right-aligned, #EA002A background with 30px border-radius
- Nav is sticky, height 80px

## Hero Section
- Headline: "Join Labrador's Leading Real Estate Team"
- Subheadline: Emphasizes national brand, local ownership, award-winning status, technology
- Badge: "Recruitment Open"
- CTA button: "Express Interest Today" (links to #contact)

## Main Sections

### 1. Why Join Us (#why-join)
Grid of 8 cards explaining value proposition:
- National Brand Power
- Local Ownership & Support
- Proven Track Record
- Technology Leadership
- Mentorship & Training
- Marketing Support
- Flexible, Competitive Commission
- Background: #111111 section

### 2. Our Track Record (#track-record)
Grid credential cards showing verified awards:
- 10× Top Ten East Coast (2016–2025)
- 9× Chairman's Club Top 1% (2017–2025)
- 4× Award of Excellence (2022–2025)
- 4× Executive Circle (2022–2025)
- 2× A.E. LePage Brokerage of Year (2018, 2020 — East Coast)
- 3× Best in Tech Division 1 (2021, 2022, 2024)

### 3. What We Offer (#what-we-offer)
6 cards detailing agent support:
- Commission Structure
- Technology Stack
- Marketing Support
- Team Coaching
- Compliance & Legal
- Mentorship Program

### 4. About Labrador West Market
Context on opportunity: underserved market, mining growth, population stabilization,
growth potential for experienced agents.

### 5. Contact / Inquiry Form (#contact)
Simple form with fields:
- Full Name (required)
- Email (required)
- Phone (required)
- License Number (optional)
- Message/Experience & Goals (optional)

Form action: JavaScript assembles mailto: link to miketurner@royallepage.ca
Subject: "Recruitment Inquiry — Lab West Office"
Body includes all form data

### Footer Bar
Red bar (#EA002A) with:
- Left: "Royal LePage Turner Realty"
- Right: "royallepageturner.com · 709-256-7999"
- Right-side links open externally or via tel:

## Site Structure
- index.html (single-page recruiting site)
- css/main.css (minimal/empty placeholder)
- js/ (optional helpers, not needed yet)
- tools/ (pre-deploy-check.py, page-template.html, etc.)
- robots.txt (standard)
- sitemap.xml (standard)
- CLAUDE.md (this file)

## Brokerage Details
- **Name**: Royal LePage Turner Realty (2014) Inc.
- **Founded**: 1998 by Gaye Turner as Turner Realty
- **Franchise**: Merged with Royal LePage 2007
- **Current Owners**: Gaye & Mike Turner (acquired 2014)
- **Broker of Record**: Mike Turner
- **Main Brokerage Address**: 204 Airport Blvd, Gander, NL A1V 1L6
- **Main Phone**: 709-256-7999
- **Three Offices**: Gander (main), Happy Valley-Goose Bay, Labrador West (this one)

## Award Highlights (from verified awards inventory)
- **Chairman's Club Top 1%**: 2017–2025 (9 consecutive years)
- **Top Ten East Coast**: 2016–2025 (10 consecutive years, best ranks #2 in 2017, #5 in 2023–2024, #6 in 2025)
- **Award of Excellence**: 2022–2025 (team award)
- **Executive Circle**: 2022–2025
- **Brokerage of the Year (East Coast)**: 2018, 2020
- **Best in Tech Division 1**: 2021, 2022, 2024
- **Lead Manager of the Year Finalist**: 2023 (Mike Turner, 5.4% close rate, 3rd nationally)

## Real Brokerage Contact
- **Broker of Record**: Mike Turner
- **Email**: miketurner@royallepage.ca
- **Phone**: 709-256-7999
- **Hub Site**: royallepageturner.com

## GA4 & Analytics
- **Measurement ID**: G-FEMZDX1BJQ
- Shared with all Turner Realty sites

## Integrations
- **GA4**: Tracking recruitment inquiries
- **Form Handler**: JavaScript mailto: assembly (no external webhooks for now)
- **External Links**: royallepageturner.com (hub site)
- **No Rechat/RealtyVis**: Not needed for recruiting site

## Responsive Breakpoint
- Mobile-first design
- Nav and sections stack/compress below 768px
- Phone pill, footer bar collapse to vertical layout on mobile

## CSS Scoping
Page uses `.lw` prefix for all styles (Lab West).
All styles are scoped inline in `<style>` block. No external stylesheets required.

## Common Mistakes to Avoid
- Mixing light theme (#fff, #f7f7f7) with dark theme (#0a0a0a, #111111) — Lab West is dark only
- Forgetting GA4 script tag
- Hardcoding phone numbers instead of using `href="tel:..."`
- Form submission attempting POST to external endpoint — use mailto: assembly instead
- Nav links not set up as anchors (#section-id)
- Missing responsive media queries for mobile navigation

## Pending Items
- None yet — site is complete and recruiting-ready

## Deployment Checklist
1. Run `python3 tools/pre-deploy-check.py` — ensure no errors/warnings
2. Verify all GA4 tracking fires correctly
3. Test form submission (mailto: link assembly)
4. Test nav anchor links on mobile
5. Verify phone pill works on mobile (clickable tel: link)
6. Test responsive breakpoints (tablet, mobile)
7. Check footer bar spacing and alignment
8. Verify all award data is accurate (cross-reference awards inventory)
9. Deploy to labwestrealty.com via Netlify
