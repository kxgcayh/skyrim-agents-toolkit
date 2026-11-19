# Local preferences

## My preferences

- **Creating a mod**. See the full rule below.

## Preference details

- **Creating a mod**. Keep the new repository in the workspace mods folder.
  Place the source and documentation together.
- **Publishing a mod**. Record the release separately.
- **Creating a mod from a template**. This longer entry has a different label.
  Keep the source template beside its documentation.
  Track the template version in the repository.

## Doc index

```json
{
  "version": 1,
  "entries": [
    {
      "id": "creating-a-mod",
      "file": "KNOWLEDGEBASE.local.md",
      "targets": ["**Creating a mod**"],
      "paths": ["/skyrim-workspace/mods/"],
      "binding": true
    }
  ]
}
```
