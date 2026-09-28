from __future__ import annotations

import math


PAIR_LIST = [
    "1-2",
    "2-3",
    "3-4",
    "4-5",

    "1-6",
    "6-7",
    "7-8",
    "8-9",

    "5-9",
]


POSITIVE_PAIRS = [
    "1-2",
    "2-3",
    "3-4",
    "4-5",
]


NEGATIVE_PAIRS = [
    "1-6",
    "6-7",
    "7-8",
    "8-9",
    "5-9",
]


MIN_POINTS_PER_PAIR = 3


def _coordinate(
    value,
    label,
):

    value = float(
        value
    )

    if (
        not math.isfinite(
            value
        )
        or
        value < 0
    ):

        raise ValueError(
            f"invalid coordinate: {label}"
        )

    return value


def convert_mark(
    mark,
):

    return {
        "a": [
            _coordinate(
                mark[
                    "x_a_px"
                ],
                "x_a_px",
            ),

            _coordinate(
                mark[
                    "y_a_px"
                ],
                "y_a_px",
            ),
        ],

        "b": [
            _coordinate(
                mark[
                    "x_b_px"
                ],
                "x_b_px",
            ),

            _coordinate(
                mark[
                    "y_b_px"
                ],
                "y_b_px",
            ),
        ],
    }


def build_phase_dataset(
    state,
    phase,
):

    if phase not in {
        "train",
        "holdout",
    }:

        raise ValueError(
            "phase must be "
            "train or holdout"
        )


    geometry = (
        state
        .get(
            "geometry",
            {}
        )
        .get(
            phase,
            {}
        )
    )


    pairs = {}


    for pair in PAIR_LIST:

        source_marks = (
            geometry.get(
                pair,
                []
            )
            or []
        )


        pairs[
            pair
        ] = [
            convert_mark(
                mark
            )
            for mark
            in source_marks
        ]


    return {
        "format":
            "smart-fire-manager-"
            "cross-preset-marks-v1",

        "phase":
            phase,

        "pairs":
            pairs,
    }


def geometry_readiness(
    state,
):

    output = {
        "minimum_points_per_pair":
            MIN_POINTS_PER_PAIR,

        "train": {},
        "holdout": {},
    }


    for phase in (
        "train",
        "holdout",
    ):

        data = build_phase_dataset(
            state,
            phase,
        )


        for pair in PAIR_LIST:

            count = len(
                data[
                    "pairs"
                ][
                    pair
                ]
            )


            output[
                phase
            ][
                pair
            ] = {
                "count":
                    count,

                "ready":
                    (
                        count
                        >=
                        MIN_POINTS_PER_PAIR
                    ),
            }


    output[
        "train_ready"
    ] = all(
        item[
            "ready"
        ]
        for item
        in output[
            "train"
        ].values()
    )


    output[
        "holdout_ready"
    ] = all(
        item[
            "ready"
        ]
        for item
        in output[
            "holdout"
        ].values()
    )


    output[
        "solver_ready"
    ] = bool(
        output[
            "train_ready"
        ]
        and
        output[
            "holdout_ready"
        ]
    )


    return output


def _select_pairs(
    dataset,
    selected,
):

    return {
        "format":
            dataset[
                "format"
            ],

        "phase":
            dataset[
                "phase"
            ],

        "pairs": {
            pair:
                dataset[
                    "pairs"
                ][
                    pair
                ]

            for pair
            in selected
        },
    }


def build_final_solver_inputs(
    state,
):

    readiness = (
        geometry_readiness(
            state
        )
    )


    if not readiness[
        "solver_ready"
    ]:

        raise ValueError(
            "Cross-Preset marks "
            "ยังไม่ครบอย่างน้อย "
            f"{MIN_POINTS_PER_PAIR} จุด "
            "ทุก pair ทั้ง Train/Holdout"
        )


    train = (
        build_phase_dataset(
            state,
            "train",
        )
    )


    holdout = (
        build_phase_dataset(
            state,
            "holdout",
        )
    )


    return {
        "positive_train":
            _select_pairs(
                train,
                POSITIVE_PAIRS,
            ),

        "negative_train":
            _select_pairs(
                train,
                NEGATIVE_PAIRS,
            ),

        "positive_holdout":
            _select_pairs(
                holdout,
                POSITIVE_PAIRS,
            ),

        "negative_holdout":
            _select_pairs(
                holdout,
                NEGATIVE_PAIRS,
            ),

        "readiness":
            readiness,

        "runtime_changed":
            False,
    }
