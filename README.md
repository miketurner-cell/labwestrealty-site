# Labrador West Realty — Royal LePage Turner Recruiting Site

A complete, production-ready recruiting website for Royal LePage Turner Realty's Labrador West office (Labrador City & Wabush, NL).

## Site Structure

### Pages
- **index.html** — Hero with compelling recruiting headline, benefits overview, awards, and CTA
- **why-join.html** — Detailed benefits: rlpSPHERE CRM, Smart Leads, training programs, marketing resources
- **about-turner.html** — Brokerage story, leadership, awards history, values, culture
- **labrador-west.html** — Market opportunity: demographics, employment drivers, why agents should join now
- **contact.html** — Inquiry form with JS-assembled mailto links, contact information

### Supporting Files
- **robots.txt** — SEO guidelines for search engines
- **sitemap.xml** — XML sitemap for indexing
- **favicon.png** — 1x1 transparent PNG favicon

## Design System

### CSS Scope
All styles use the `.lw` prefix for scoped styling, matching the corporate light theme from royallepageturner-site.

### Colors
- **Background**: #fff (white)
- **Accent**: #EA002A (red), #c8001f (hover)
- **Text**: #1a1a1a (headings), #2c2c2c (body), #666 (secondary)
- **Borders**: #e8e8e8 (subtle), #ddd (inputs)

### Typography
- **Headings**: Raleway 800/900
- **Body**: Roboto 300/400
- **Imported from Google Fonts**

### Responsive Breakpoints
- **Desktop**: Full width (1100px content max)
- **Tablet**: max-width 1024px (adjusted nav, single column grids)
- **Mobile**: max-width 600px (stacked layout, hidden nav elements)

## Key Features

### Navigation
- Sticky header with responsive hamburger toggle
- Smooth navigation across all pages
- Phone number in nav (709-256-7999)
- Scoped nav markup (`.nav-bar`, `.nav-toggle`, `.nav-links`)

### Forms & JavaScript
- Contact form with JS-assembled mailto links (email not plaintext in HTML)
- Form submission redirects to email client with pre-filled subject/body
- License status dropdown with relevant options
- Mobile menu toggle functionality

### SEO & Analytics
- Meta tags (title, description, og:tags) on every page
- Canonical URLs for each page
- Google Analytics 4 (G-FEMZDX1BJQ)
- Structured data (JSON-LD) on contact page
- XML sitemap for search indexing

### Footer
- Consistent footer across all pages
- Red footer bar with brokerage name, URL, phone
- Links to Turner Realty network (Gander, Happy Valley-Goose Bay, main network)
- Copyright and legal disclaimer
- "Part of Royal LePage Turner Realty" branding

## Credentials Featured

- Royal LePage Turner Realty (2014) Inc. — Founded 1998
- Broker of Record: Mike Turner (licensed 2009, BOR since 2022)
- Chairman's Club Top 1% nationally (9 consecutive years)
- #43 nationally by units (2025)
- Top Ten East Coast Team (10 consecutive years)
- 3× Best in Tech (2021, 2022, 2024)
- Award of Excellence & Executive Circle (2022–2025)
- 2× A.E. LePage Brokerage of the Year, East Coast (2018, 2020)
- Lead Manager of the Year Finalist (2023)
- 3 offices across NL, 11 REALTORS®

## Contact Information

**Brokerage**
Royal LePage Turner Realty (2014) Inc.
204 Airport Boulevard
Gander, NL A1V 1L6
Phone: 709-256-7999
Email: miketurner@royallepage.ca

## Technology Stack

- Pure HTML5 (no build tools, no dependencies)
- Vanilla CSS (responsive, mobile-first)
- Vanilla JavaScript (form handling, mobile menu, mailto assembly)
- Google Fonts (Raleway, Roboto)
- Google Analytics 4

## Browser Support

- Chrome/Edge (latest 2 versions)
- Firefox (latest 2 versions)
- Safari (latest 2 versions)
- Mobile browsers (iOS Safari, Chrome Android)

## Deployment

Deploy all files to labwestrealty.com root directory. No build step required.

---

**Created**: April 4, 2026
**Status**: Production-ready
**Last Updated**: April 4, 2026
