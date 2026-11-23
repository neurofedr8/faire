# Deriving a dataset template

This is faire's base dataset template: the fixed CI, `.gitattributes` and an answers file,
and no rule or check. To make a template of your own:

1. Copy this directory into a new git repository (or start from `standard` or `derivative`,
   which are copies of it with placeholder rules).
2. Add the questions your template needs to `copier.yml`; the ma-DMP answers them in
   `faire.template.data`.
3. Declare a container collection and your rules and checks in `.datalad/config`
   (see the commented example there).
4. To keep commit dates from disclosing when data was acquired, enable DataLad fake dates
   with `datalad.fake-dates = true` in `.datalad/config`: faire then fake-dates every commit
   and tag from the dataset's first, and `faire release` fails on any real date. Storage
   remotes that run git-annex themselves (siblings over SSH) currently record real dates in
   the `git-annex` branch.
5. Keep `.gitlab-ci.yml` as is: it only runs `faire plan` and executes its output.
6. Tag a version and reference repository and tag from the ma-DMP.

This file is excluded from rendered datasets.
