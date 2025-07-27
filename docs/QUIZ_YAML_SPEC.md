# Quiz YAML Format

This project stores each quiz definition in a YAML file. The expected schema is inspired by `quizzes/sample_ninja_turtles.yaml` and the build specification. A quiz file contains the following top-level keys:

- `id` – a slug style identifier for the quiz.
- `title` – the human readable quiz title.
- `source` – an object with `publication` and `url` fields describing where the quiz came from.
- `notes` – freeform notes about usage or licensing.
- `questions` – list of question objects.
- `outcomes` – optional list of scoring rules.

Each question entry has:

- `id` – unique question identifier.
- `text` – question text.
- `options` – list of answer options. Each option may include:
  - `id` – letter or short identifier.
  - `text` – the option text.
  - `tags` – optional list of category tags.
  - `score` – optional numeric value used by some scoring rules.

An outcome entry describes how to infer the final result. Common `condition` keys are:

- `mostly` – the letter chosen most often.
- `mostlyTag` – the tag that appears most often among chosen options.
- `scoreRange` – `{ min, max }` range for the summed option scores.

The `result` field is freeform text shown when the condition is met. Only the first matching rule is applied.

This format is flexible enough for most magazine-style personality quizzes and is what the CLI expects when running benchmarks.
