/*
  Given an accession number and MRN get the associated radiology report
 */

set search_path to ${{ schema_name }}, public;

select
  string_agg(lr.value_as_text, '' order by
      case ltd.test_lab_code
          when 'ADDENDA' then 1
          when 'NARRATIVE' then 2
          when 'IMPRESSION' then 3
      end
  ) AS report

from lab_sample as ls
join lab_order as lo using(lab_sample_id)
join lab_result as lr using(lab_order_id)
join lab_test_definition as ltd using(lab_test_definition_id)
join mrn using(mrn_id)

where ls.external_lab_number = :accession_number
    and mrn.mrn = :mrn
    and ltd.test_lab_code in ('ADDENDA','NARRATIVE','IMPRESSION')