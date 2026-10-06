# Fictional rehearsal inputs

These files contain fabricated ownership, amounts and prices, not personal holdings or current market quotes. TCS/INFY identifiers come from the repository's stored universe. Dates are 6 October 2026; update them truthfully if the rehearsal date changes.

- [holdings-fictional.csv](holdings-fictional.csv): five valid rows, ₹2,32,000 total reported value. Use preview in a newly created fictional account. Identity resolution depends on the catalogue/instruments already loaded in that demo database.
- [holdings-invalid-date.csv](holdings-invalid-date.csv): intentionally invalid date; preview should show an error and prevent confirmation. It is a failure-case demonstration.
- [profile-facts.json](profile-facts.json): schema-valid fictional facts, aggressive behavioural answers and ₹1,00,000 reserve.

Enter a separate fictional liability with ₹5,000 monthly payment and ₹1,50,000 outstanding amount through Financial profile. With that payment, outgo is ₹25,000 and reserve covers four months versus a six-month target. Without that liability, the profile has different arithmetic. These inputs do not automatically create goals, price history or a ready stock ranking.

The JSON is the facts object, not a complete update request. API profile updates require the actual current `expected_version` and a `facts` wrapper; the UI handles those. Do not overwrite a personal profile. A normal plan should respect reserve constraints even though tolerance is aggressive. Add a fictional goal and an active commitment through the UI if demonstrating projections.

Verified with the current pure import parser and FinancialFacts schema: valid rows accepted; invalid date rejected; tolerance aggressive; reserve months 4.0 when the specified liability is supplied. No imports were written to a running database by this verification.
