prompt: b_products v3

Target: Table B, one record per loan product reviewed. The record key is the product label in lower case, for example "home mortgage", "small business", "small farm", "consumer", or the printed name for other products. Use the same key for every fact about the same product.

Field guide:
- product: one of "home mortgage", "small business", "small farm", "consumer", "other".
- is_major_product: "1" if the evaluation identifies the product as a major/primary product line, "0" if it explicitly says it is not major, otherwise omit. weight_text: the verbatim sentence explaining relative weight. printed = "" for is_major_product.
- data_source: ALWAYS give this when the evaluation says how the product's data were obtained (examiners selected a sample of loans -> "examiner sample"; the bank reports HMDA data -> "HMDA"; reported CRA data -> "CRA-reported data"; reviewed all loans from the bank's own records -> "complete bank records"); use "unclear" only when the text is ambiguous. One of "HMDA", "CRA-reported data", "complete bank records", "examiner sample", "unclear", from what the evaluation says was used for that product; data_source_verbatim: the supporting sentence verbatim.
- universe_count, sample_count: counts exactly as printed (integers, printed without units). universe_dollars, sample_dollars: as printed with symbols and units.
- loan_years: the origination years covered, as printed. eval_period_start, eval_period_end: the product-specific period when it differs.
- inside_aa_count_pct, inside_aa_dollar_pct: percentages of loans (by number, by dollars) INSIDE the assessment area, taken from the inside/outside table; printed = the percent exactly as written, for example "93.3%".


Universe versus sample: `universe_count`/`universe_dollars` describe ALL loans of that product in scope (the population the bank originated or purchased). `sample_count`/`sample_dollars` describe the subset the examiners actually reviewed. "A random sample of 180 commercial loans" means sample_count 180 and the universe is NOT stated unless a separate, larger population figure is printed. When the evaluation reviewed every loan (for example all HMDA-reportable loans), report that population as the universe and leave the sample empty. Never put a sample's figures in the universe fields, and never copy the same figures into both.
