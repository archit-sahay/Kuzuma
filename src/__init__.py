# Initialize logger when the src package is imported
from .logger import init_logger as __initialize_logger__

# Initialize the logger early in the package lifecycle
__initialize_logger__()
