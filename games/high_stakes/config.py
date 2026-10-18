from gameengine.data import default_root
from gameengine.config import AsgConfig

CONFIG = AsgConfig(
    key="high-stakes",
    display_name="Dick Francis: High Stakes",
    root=default_root("high_stakes"),
    table_record_size=40,
    text_attribute=0x0E,  # yellow on the original screen (B800)
)
