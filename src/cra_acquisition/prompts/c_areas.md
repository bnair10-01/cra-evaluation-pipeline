prompt: c_areas v2

Target: Table C, one record per assessment area (AA) named in the evaluation. The record key is the AA name as printed. Use the same key for every fact about the same area.

Field guide:
- aa_name: ALWAYS give this for every area. It is the short name the evaluation uses for the area (for example "Honolulu AA", "CNB AA", "Dubuque MSA", "Southern Mississippi"), never a whole sentence. If the evaluation names the area only inside a sentence, quote that sentence as evidence and put just the name in value. state: the state as printed. msa_or_nonmsa: the printed designation (MSA name/number or non-MSA wording).
- review_scope: "full scope" or "limited scope" as the evaluation states for this area.
- counties: the counties of the area as printed. tract_list: census tract numbers if listed (keep the printed form; if the list is in an appendix, quote the first line of the list and state its page).
- tract_counts_by_income: a JSON object text with keys "low", "moderate", "middle", "upper", "not_available" holding the printed tract counts (use null for counts not printed, 0 only when 0 is printed). Quote the sentence or table row that contains the counts. printed = "".
- census_vintage: the census or ACS source/vintage used for the demographic measures, verbatim.
