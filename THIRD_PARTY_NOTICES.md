# Third-party notices

The root MIT license applies to project-owned software and documentation. It does not replace the terms below. Existing third-party files, copyright headers and historical source records have not been relicensed or removed.

| Material | Location / origin | License and attribution |
| --- | --- | --- |
| Three.js 0.170.0 and OrbitControls/STLLoader | `simulator/vendor/` | MIT; retain [original license](simulator/vendor/LICENSE) |
| Community robot arm models and graphics | `mechanical/upstream/community_robot_arm/`, [20sffactory upstream](https://github.com/20sffactory/community_robot_arm), based on Florin Tobler's RobotArm | CAD/graphics: CC BY 4.0 according to retained upstream README; identify adaptations and retain attribution |
| Community robot arm firmware reference | Same upstream directory, fixed commit `6c2f57390f0186f47bb199f06c875dedf8de268f` | GPL-3.0; [original license](mechanical/upstream/community_robot_arm/LICENSE) remains in place; root MIT does not apply |
| Linear-stage driver | `drivers/micropython/linear_stage/`, [historical source](https://github.com/FreakStudioCN/micropython-linear-stage) | MIT, existing RobotArm UART contributors attribution; original LICENSE retained in-tree; historical commit 8b184a4 and non-squashed source history recorded in hardware/linear_stage/provenance.json |
| Installed Python/Conda/FFmpeg tooling | Dependency files and the user's runtime environment | Separately distributed dependencies retain their own licenses, including build-dependent FFmpeg terms |

Model provenance, original references, the pinned commit and hashes are retained in [PROVENANCE.md](mechanical/upstream/community_robot_arm/PROVENANCE.md) and the upstream manifest. Self-authored photo reconstruction is marked as estimated in [its documentation](mechanical/photo_reconstruction/README.md); it does not change the upstream model's license. Original CAD, imported references and supplier material require their own provenance when redistributed.

The historical root copyright holder `RobotArm UART contributors` is retained because a repository rename or a different Git committer is not evidence of a copyright transfer.

README images are selected project-supplied engineering illustrations; [asset notes](docs/assets/readme/README.md) describe their processing. Depicted products and marks remain their owners' property. A photograph does not grant rights to redistribute an unrelated product's design.
