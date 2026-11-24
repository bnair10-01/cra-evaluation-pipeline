prompt: a_exam v2

Target: Table A, exam-level facts for the whole evaluation. Use the single record key "A" for every fact.

Field guide (use exactly these field names):
- agency: the regulator named on the cover (OCC, FDIC, Federal Reserve, OTS as printed).
- institution_name: the bank's name as printed on the cover.
- agency_id: the charter number (OCC) or FDIC certificate number printed in the evaluation; digits only as printed. Report an RSSD only if it is explicitly labelled and then only in the quote; do not put it here.
- exam_date: the examination (or "public disclosure"/"as of") date printed on the cover. value = ISO YYYY-MM-DD when a complete date is printed; printed = the date exactly as written. If incomplete, value = as printed.
- eval_period_start, eval_period_end: the evaluation period boundaries. When tests or products have different periods, report the broadest interval here (earliest start, latest end) only if both are printed; otherwise omit.
- exam_type: one of "small", "intermediate small", "large", "other", chosen from the printed procedure wording; exam_type_verbatim: the exact printed wording (for example "Intermediate Small Bank" or "Interagency Small Institution Examination Procedures"). Use "other" for wholesale, limited-purpose, or strategic-plan institutions. Use the procedure the evaluation itself names: for example "will utilize Large Bank CRA evaluation procedures" means large, "Interagency Small Institution Examination Procedures" or "Small Bank" means small, "Intermediate Small Bank" means intermediate small. If the evaluation never names the procedure, leave exam_type out; do not infer it from bank size or from the tests discussed.
- rating_overall, rating_lending, rating_cd, rating_investment, rating_service: the rating labels exactly as printed ("Satisfactory", "High Satisfactory", ...). Omit a rating that does not apply.
- cd_test_optional_elected: value "1" if the evaluation says the bank elected the optional Community Development test, "0" if it says the bank did not elect it, and omit the fact when not stated. Quote the supporting sentence. printed = "".
- prior_exam_date, prior_rating: the prior evaluation's date and rating when stated (usually in the institution description).
- total_assets_stated, as_of_date: total assets exactly as printed with the units, and the "as of" date.
- ltd_avg, ltd_quarters, ltd_low, ltd_high: the bank's loan-to-deposit measures as printed (for example "76.10 percent"), the number of quarters, and the low/high of the range. These are the BANK's figures, not the peers'.
- hmda_status_text: a verbatim sentence stating that the bank reports under HMDA or is exempt (fully or partially).
- community_contact_text, credit_needs_text: the verbatim paragraph(s) describing community contacts and identified credit needs.
