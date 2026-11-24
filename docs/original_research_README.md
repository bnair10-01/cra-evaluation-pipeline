# CRA research tables

The empty database implements Tables A through E from the supplied guide. No PDFs have been read, downloaded, or processed, and no research records have been populated.

## Files

- `cra_tables.sqlite`: ready-to-use SQLite database.
- `schema.sql`: reproducible table definitions and constraints.
- `data_dictionary.md`: columns, storage types, and conventions.

## Relationships

Table A has one row per evaluation. Table B has one row per reviewed product and applicable source/period context; repeat a product where contexts differ. Table C has one row per assessment area. Table D has one row per evaluation, assessment area, product context, dimension, category, and reported period. Table E has one row per distinct examiner conclusion and context. Each table joins through `pe_id`; D and E can also link to B and C.

The guide's `ltd_peers` field is represented by a child table so each named peer can have its own row. `field_evidence` stores page references and verbatim support at field level without repeating evidence columns throughout all five tables.

IDs, `exam_type_verbatim`, `data_source_verbatim`, product-specific evaluation dates, and conclusion context columns are structural additions needed to implement the guide. The requested research fields are retained. This is an initial schema, not an extraction pipeline.

Enable `PRAGMA foreign_keys = ON` on every SQLite connection. Links to products and assessment areas must belong to the same evaluation. Back up the database before adding data. The evidence table's polymorphic record and field references require application validation; SQLite does not enforce those references.
