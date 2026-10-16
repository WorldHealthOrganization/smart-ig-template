# WHO SMART Guidelines FHIR IG Template

**This template may only be used for ImplementationGuides that are authored by the World Health Organization.**

## Translations

The template builds on `fhir2.base.template`, which renders each IG language in its own folder (`en/`, `fr/`, ...).
Text that the WHO template adds to pages must not be hard-coded in English:

- add the English text to `translations/stringsWHO.json` under a new key
- add the key with its translation to each `translations/stringsWHO-<lang>.po` (`fr`, `es`, `ar`, `ru`, `zh`)
- in includes and layouts, read it from `site.data.stringsWHO[lang]`, for example
  `{% assign whoStrings = site.data.stringsWHO[include.lang] | default: site.data.stringsWHO.en %}{{whoStrings.Form}}`

The IG Publisher merges the `.po` files into `site.data.stringsWHO`, falling back to English for missing entries.
Texts that come from the base template use `site.data.stringsBase` and are translated in the base template.

 
 
