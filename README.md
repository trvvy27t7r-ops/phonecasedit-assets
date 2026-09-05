# phonecasedit-assets

Public 3D assets for the PhoneCaseEdit hero.

## Automated Blender build

GitHub Actions runs Blender headlessly to preserve the source phone, construct
the independent `vinyl_back` and `case_clear` layers, render four QA views, run
the official Khronos glTF validator, and publish the validated result.

- Source: `iphone_17_pro_max (1).glb`
- Final generated asset: `dist/iphone-17-pro-max-hero.glb`
- Visual checks: `qa/`
- Machine-readable checks: `reports/`
- Source attribution: [`ATTRIBUTION.md`](ATTRIBUTION.md)

The workflow refuses to publish if validation reports errors, if any expected
QA render is missing, if the GLB exceeds 5 MiB, or if the scripted geometry
exceeds 50,000 triangles.
