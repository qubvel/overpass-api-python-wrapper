import requests

class Nominatim(object):
	"""Nominatim helper class, for lookups"""

	from .errors import NominatimError

	url_template = "https://nominatim.openstreetmap.org/search?format=json&q={name}"
	min_confidence = 0.8

	@classmethod
	def lookup(self, name):
		lookup_url = self.url_template.format(name=name)
		try:
			response = requests.get(lookup_url)
			nominatim_results = response.json()
			for result in nominatim_results:
				if result.get("importance") >= self.min_confidence:
					return result
			return {}
		except Exception as e:
			raise NominatimError(e.message)