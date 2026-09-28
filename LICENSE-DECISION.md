# License Decision

The project imports and depends on the `ultralytics` package and uses an Ultralytics YOLO workflow/model artifact.

Before the repository is presented as a distributable open-source release, verify which Ultralytics license applies.

## Open-source path

If the project uses Ultralytics under its AGPL-3.0 open-source terms, use an AGPL-3.0-compatible license for the complete repository and distribute the corresponding source required by those terms.

Recommended repository metadata in that case:

```text
SPDX-License-Identifier: AGPL-3.0-only
```

Add the official GNU Affero General Public License v3.0 text as the repository `LICENSE` file.

## Commercial / proprietary path

If you hold another applicable Ultralytics commercial/enterprise license, document that basis before selecting a different project license.

## Also verify redistribution rights for

- custom trained model weights
- training / validation datasets
- example images and videos
- vendor screenshots/software
- fonts/icons/logos
- third-party code copied into the project
