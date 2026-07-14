# Model files go here

The classifier expects one current bundle in this directory:

model/
└── current/
    ├── model.tflite    # AIY/Coral iNaturalist birds, MobileNetV2, quantized
    └── labels.txt      # matching labels, one species per line

## Where to get them

These come from Google's Coral test-data repo. From the Perch project root, use
the checked-in helper so both downloads are verified before they replace any
existing model files:

    ./scripts/download-model.sh

The script pins the source URLs and SHA-256 checksums, stages both files in a
sibling directory, and promotes that directory as `current`. If promotion is
interrupted, it restores the previous complete bundle.

Existing installations that have files directly under `classifier/model/`
must rerun `./scripts/download-model.sh` once to create the current bundle.

## Runtime policy

MobileNetV2 is Perch's stable runtime. ONNX models are experimental future
work and are not supported by the production container. They need a separate
runtime image, model-specific preprocessing, bird cropping, and Pi benchmarks
before they can be considered for the stable path.

## Label format

One label per line; the line number is the class index. Reads like:

    Haemorhous mexicanus (House Finch)
    Cardinalis cardinalis (Northern Cardinal)

`classify.py` parses `Scientific name (Common Name)` into separate fields and
treats any `background` class as "no bird." An optional numeric index prefix
(`0 background`) is also handled.

## Override paths

If you keep the files elsewhere, point the classifier at them with
`MODEL_PATH` and `LABELS_PATH` in your `.env`.
