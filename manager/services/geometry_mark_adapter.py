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


# Stage 3F: explicit, LAB-only source-session dataset. Never silently
# incorporate legacy coordinates into current camera frames.
def historical_draft_solver_inputs(site_id, *, evidence_provider=None):
    import hashlib, json
    from manager.services.phase45_editor import (_LEGACY_SITE, _LEGACY_REV, legacy_draft_preview)
    from manager.services.runtime_site_crud import _require_editable_working_copy
    if site_id != _LEGACY_SITE:
        raise PermissionError('HISTORICAL_SOLVER_SITE_NOT_SUPPORTED')
    working = _require_editable_working_copy(site_id)
    if working.get('parent_revision') != _LEGACY_REV or working.get('recovery'):
        raise PermissionError('HISTORICAL_SOLVER_WRONG_WORKING_COPY')
    get_pair = evidence_provider or legacy_draft_preview
    phases = {}
    fingerprints = {}
    readiness = {'minimum_points_per_pair': MIN_POINTS_PER_PAIR, 'train':{},'holdout':{}}
    for phase in ('train', 'holdout'):
        pairs = {}
        for pair in PAIR_LIST:
            view = get_pair(phase,pair)
            if (view.get('site_id')!=site_id or view.get('revision_id')!=_LEGACY_REV
                or view.get('phase')!=phase or view.get('pair')!=pair
                or view.get('source_equals_active_images') is True
                or view.get('draft',{}).get('editable') is not True):
                raise RuntimeError('HISTORICAL_SOLVER_PROVENANCE_OR_EDITABLE_REJECTED:'+phase+':'+pair)
            points = view['draft']['effective_marks']
            if not isinstance(points,list) or not MIN_POINTS_PER_PAIR<=len(points)<=400:
                raise ValueError('HISTORICAL_SOLVER_POINTS_INSUFFICIENT:'+phase+':'+pair)
            # Every position is from one audited source-session frame. Validate each
            # side against its own dimensions rather than the current PTZ image.
            dims = view['source_dimensions']
            a,b = dims['a'],dims['b']
            clean = []
            for mark in points:
                for side,wh in (('a',a),('b',b)):
                    x,y=mark['x_'+side+'_px'],mark['y_'+side+'_px']
                    if (type(x) not in (float,int) or type(y) not in (float,int)
                        or not math.isfinite(x) or not math.isfinite(y)
                        or not (0<=x<wh[0] and 0<=y<wh[1])):
                        raise ValueError('HISTORICAL_SOLVER_BAD_COORDINATE:'+phase+':'+pair)
                clean.append(convert_mark(mark))
            pairs[pair]=clean
            readiness[phase][pair]={'count':len(clean),'ready':True}
            fingerprints[phase+':'+pair]={
                'source_marks_sha256':view['source_marks_sha256'],
                'mixed_sha256':view['mixed_sha256'],
                'session':view['source_session'],
                'draft_digest':view['draft']['digest'],
                'count':len(clean),
                'image_dimensions':{side:list(dims[side]) for side in ('a','b')},
            }
        phases[phase]={'format':'smart-fire-manager-cross-preset-marks-v1','phase':phase,'pairs':pairs}
    # Holdout must be from a different evidence session than Train per pair.
    for pair in PAIR_LIST:
        if fingerprints['train:'+pair]['session']==fingerprints['holdout:'+pair]['session']:
            raise ValueError('HISTORICAL_HOLDOUT_NOT_INDEPENDENT:'+pair)
    readiness.update(train_ready=True,holdout_ready=True,solver_ready=True)
    outputs={
        'positive_train':_select_pairs(phases['train'],POSITIVE_PAIRS),
        'negative_train':_select_pairs(phases['train'],NEGATIVE_PAIRS),
        'positive_holdout':_select_pairs(phases['holdout'],POSITIVE_PAIRS),
        'negative_holdout':_select_pairs(phases['holdout'],NEGATIVE_PAIRS),
    }
    blob=json.dumps({'fingerprints':fingerprints,'inputs':outputs},sort_keys=True,separators=(',',':')).encode()
    return {**outputs, 'readiness':readiness,'dataset_digest':hashlib.sha256(blob).hexdigest(),
            'fingerprints':fingerprints,'site_id':site_id,'parent_revision':_LEGACY_REV,
            'source':'historical_draft_lab_only','runtime_changed':False,'production_certified':False,
            'field_accuracy_proven':False}
