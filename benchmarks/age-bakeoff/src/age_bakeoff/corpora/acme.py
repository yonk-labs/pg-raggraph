from age_bakeoff.extraction.loaders import load_acme_extraction
from age_bakeoff.models import ExtractionOutput


class AcmeCorpus:
    name = "acme"

    def load(self) -> ExtractionOutput:
        return load_acme_extraction()
