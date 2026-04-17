from age_bakeoff.extraction.loaders import load_scotus_extraction
from age_bakeoff.models import ExtractionOutput


class ScotusCorpus:
    name = "scotus"

    def load(self) -> ExtractionOutput:
        return load_scotus_extraction()
