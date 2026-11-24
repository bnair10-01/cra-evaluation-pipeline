prompt: e_conclusions v3

Target: Table E, one record per examiner conclusion. Use a unique key per conclusion within this response ("E1", "E2", ...); put every field belonging to the same conclusion under the same key.

A conclusion is a sentence or short passage in which the examiner judges performance on a criterion: loan-to-deposit ratio, lending inside the assessment area, geographic distribution, borrower distribution (income of borrowers or revenue size of businesses/farms), responsiveness to complaints, community development lending/investments/services, and overall test conclusions.

Field guide:
- criterion: the measure being judged, as the evaluation names it. category: the income category or revenue class when the judgment is for one category (low, moderate, middle, upper, ...), otherwise omit.
- years: the period the judgment covers when stated.
- label_verbatim: the exact evaluative phrase, copied from the page, WITHOUT the sentence's subject and surrounding clauses. Keep the verb or qualifier that belongs to the judgment (for example "reflects reasonable distribution", "reasonable", "poor", "excellent penetration", "substantial majority", "outstanding record"). Do not output a whole sentence such as "A substantial majority of the bank's loans are inside its AAs"; the surrounding words belong in the quote, not the value. Never paraphrase.
- level: "criterion" when it covers the whole criterion, "income category" when it covers one category, "overall assessment" when it combines several measures.
- benchmark_emphasis_text: the verbatim sentence in which the examiner says it placed greater weight on aggregate lending or on demographic comparators.
- context_reasons_text: the verbatim sentence(s) explaining the result (housing costs, competition, poverty, loan volume, distance, ...).
- aa_ref: the assessment area name as printed when the judgment is specific to one area; product_ref: the product label when specific to a product ("home mortgage", "small business", "small farm", "consumer"). These two are references, not data: printed = "". Omit them when the conclusion is institution-wide or the context is not stated.
Do not include prior-examination judgments or general background as current conclusions. Report quoted prior judgments only if they are clearly labelled as current.


BE EXHAUSTIVE. This table is scored on recall: every judgment you skip is an error, and a long pages list does not excuse stopping early. Emit one record for EVERY evaluative judgment on these pages, at every level of detail:
- each test-level and overall conclusion (Lending Test, Community Development Test, Investment/Service Test, state or multistate conclusions);
- each criterion (loan-to-deposit ratio, lending inside the assessment area, geographic distribution, borrower distribution, responses to complaints, discrimination and fair-lending statements);
- separately for each assessment area and each loan product (home mortgage, small business, small farm, consumer) when the evaluation discusses them separately;
- separately for each income category sentence ("lending to low-income borrowers ... reflects poor distribution") with `category` and level "income category";
- the examiner's overall assessment sentence after each product discussion.
A single page of table commentary commonly holds three to six judgments. If one sentence makes several judgments, write one record for each. Do not output definitions, prior-examination statements, or the bank's description. Use the same wording the evaluation uses for criterion names.
