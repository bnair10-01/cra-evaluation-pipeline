prompt: d_columns v1

Target: distribution tables whose income CATEGORIES RUN ACROSS THE PAGE and whose ROWS are measures. You do NOT read any numbers; software reads them afterwards. Typical examples:

    Low-      Moderate-  Middle-   Upper-
    Income    Income     Income    Income    Total
    Total Number of Loans            50   49   30   41   170
    Percentage of Total Loans        29.5% 28.8% 17.6% 24.1% 100%
    Percentage of Area Families      29.1% 26.4% 26.3% 18.2% 100%

Only report tables of this shape (categories across, one measure per row, every value on a single text line). Do NOT report tables where the categories are rows down the side, tract lists, or housing-cost tables; another step handles those.

For each such table:
- page: the physical PDF page. table_label: the printed label ("" if none). title: the printed title ("" if none).
- dimension: "borrower income", "business revenue", "farm revenue" or "census tract income".
- aa_ref: the assessment area it belongs to ("" if the evaluation covers one area). product_ref: "home mortgage", "small business", "small farm", "consumer" or the loan type ("" if unclear). years: the printed period ("" if none). source_note: the printed source line ("" if none).
- categories: the category of EACH numeric value on a data row, left to right, as one of low, moderate, middle, upper, not available, at or below $1 million, above $1 million, or "" for a column that is not a category (for example Total). The list must have exactly as many entries as numbers on a data row.
- rows: one entry per data row you want read: line = the line number (the M of [pN.lM]) of the line that holds the NUMBERS; meaning = what the numbers are: bank_count (number of the bank's loans), bank_count_pct (percent of the bank's loans), bank_dollars (dollar amount of the bank's loans), bank_dollar_pct (percent of the bank's dollars), aggregate_pct (all-lender percent), demographic_pct (percent of the area's families, households, businesses, farms, geographies...); label = the printed row label, copied exactly ("" if none). A label may sit on the line above the numbers; copy it anyway.
Skip rows that are not one of those six meanings. Report nothing when no table of this shape is on the pages.
