"""Print the merged GraphHopper custom model for the two example telemetry rules."""
import json
from datetime import datetime, timezone
from routing import Op, SegmentIs, Source, Statement, Target, baseline_model, merge_models, to_graphhopper

now = datetime.now(timezone.utc)
overlays = [
    Statement(Target.SPEED, SegmentIs("15933"), Op.LIMIT_TO, 15, Source.TELEMETRY_SPEED, "tele.speed.15933"),
    Statement(Target.PRIORITY, SegmentIs("8442"), Op.MULTIPLY_BY, 0.01, Source.TELEMETRY_DEVIATION, "tele.dev.8442"),
]
print(json.dumps(to_graphhopper(merge_models(baseline_model(), [overlays], now), {}, segment_mode="expression"), indent=2))
