# Paper Trader visual system

Mood: graphite trading desk, warm white typography and the existing signal-green accent.
Layout: an open portfolio workspace with a compact automation summary and a separate decision journal.
Signature: large tabular account figures, thin dividers and a continuous market-status line.

## Tokens

All primary-workspace tokens are defined once in frontend/src/globals.css. Use these CSS variables throughout the primary workspace. The research workspace retains its existing theme.

| Token                       | Value                                        |
| --------------------------- | -------------------------------------------- |
| --canvas                    | #141614                                      |
| --surface                   | #1b1e1b                                      |
| --surface-hover             | #252a25                                      |
| --text                      | #f0f0e9                                      |
| --muted                     | #b3b9b1                                      |
| --line                      | #3b423a                                      |
| --accent                    | #77dfb5                                      |
| --accent-ink                | #102019                                      |
| --font                      | Manrope, sans-serif                          |
| --space-1 through --space-8 | 4px, 8px, 12px, 16px, 24px, 32px, 48px, 64px |
| --radius                    | 4px                                          |
| --ease                      | 180ms ease-out                               |

Use one font family with tabular figures for prices. Type sizes are 12, 14, 16, 18, 20, 24, 32, 40, 48, 64 and 80px. Body text is 16px with 1.6 line height. Use 14px for table data and 12px only for supporting metadata. Headings use tight leading and weights 500-700. Text is left aligned; numeric table columns align right. No status color beyond the single accent; gains and losses remain legible through signed amounts and text labels.

## Layout and behavior

Keep the account overview and trading workspace ahead of long activity logs. At 1120px and above, the workspace and decision journal form two columns; below that they stack. At 768px, account summary and automation form two columns. At 390px, navigation scrolls within its own region, forms use two columns with full-width exceptions, and only data tables may scroll horizontally. The page itself must not overflow horizontally. Use the 4px/8px scale, a 1440px maximum content width and a minimum 44px interactive target.

Sections are cardless: use whitespace and hairline separators. No gradients, tinted status pills, fake performance charts, decorative counters, drop shadows or ornamental copy. Lucide icons support navigation and real actions. Use native labeled form controls and semantic tables. Every action has hover and visible keyboard-focus states; respect reduced motion. Preserve the existing API contracts, paper-only execution, account history and risk settings.
