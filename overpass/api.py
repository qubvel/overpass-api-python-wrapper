import requests
import json
import geojson

from .errors import (OverpassSyntaxError, TimeoutError, MultipleRequestsError,
                     ServerLoadError, UnknownOverpassError, ServerRuntimeError,
                     ApiWrapperError, NominatimError)
from .helpers import Nominatim

class API(object):
    """A simple Python wrapper for the OpenStreetMap Overpass API"""

    SUPPORTED_FORMATS = ["geojson", "json", "xml"]

    # defaults for the API class
    _timeout = 25  # seconds
    _endpoint = "http://overpass-api.de/api/interpreter"
    _debug = False
    _query = None
    _responseformat = "geojson"
    _area = None
    _area_id = None
    _status = None

    _QUERY_TEMPLATE = "[out:{out}];{query}out body;"
    _GEOJSON_QUERY_TEMPLATE = "[out:json];{query}out body geom;"

    def __init__(self, *args, **kwargs):
        self.endpoint = kwargs.get("endpoint", self._endpoint)
        self.timeout = kwargs.get("timeout", self._timeout)
        self.debug = kwargs.get("debug", self._debug)
        self.area = kwargs.get("area", self._area)
        self.responseformat = kwargs.get("responseformat", self._responseformat)
        self.query = kwargs.get("query", self._query)

        # set up debugging
        if self.debug:
            import logging
            try:
                import http.client as http_client
            except ImportError:
                # Python 2
                import httplib as http_client
            http_client.HTTPConnection.debuglevel = 1

            # You must initialize logging, otherwise you'll not see debug output.
            logging.basicConfig() 
            logging.getLogger().setLevel(logging.DEBUG)
            requests_log = logging.getLogger("requests.packages.urllib3")
            requests_log.setLevel(logging.DEBUG)
            requests_log.propagate = True

    @property
    def area(self):
        return self._area

    @area.setter
    def area(self, val):
        if val:
            self._area = val
            nominatim_result = Nominatim.lookup(val)
            area_id = self._toAreaId(nominatim_result)
            self.area_id = area_id

    @property
    def area_id(self):
        return self._area_id

    @area_id.setter
    def area_id(self, val):
        self._area_id = val

    @property
    def query(self):
        return self._query

    @query.setter
    def query(self, val):
        self._query = val
        if val:
            self._raw_query = self._ConstructQLQuery(val)

    @property
    def responseformat(self):
        return self._responseformat

    @responseformat.setter
    def responseformat(self, val):
        self._responseformat = val

    @property
    def raw_query(self):
        return self._raw_query

    @raw_query.setter
    def raw_query(self, val):
        self._raw_query = val

    def Get(self, query=None):
        """Pass in an Overpass query in Overpass QL"""

        query = self._ConstructQLQuery(query) or self.raw_query

        if not query:
            raise ApiWrapperError('No query')
            return False

        # Get the response from Overpass
        raw_response = self._GetFromOverpass(query)

        if self.responseformat == "xml":
            return raw_response
            
        response = json.loads(raw_response)

        # Check for valid answer from Overpass. A valid answer contains an 'elements' key at the root level.
        if "elements" not in response:
            raise UnknownOverpassError("Received an invalid answer from Overpass.")

        # If there is a 'remark' key, it spells trouble.
        overpass_remark = response.get('remark', None)
        if overpass_remark and overpass_remark.startswith('runtime error'):
            raise ServerRuntimeError(overpass_remark)

        if self.responseformat is not "geojson":
            return response

        # construct geojson
        return self._asGeoJSON(response["elements"])

    def Search(self, feature_type, regex=False):
        """Search for something."""
        raise NotImplementedError()

    def _ConstructQLQuery(self, query):
        query = str(query)
        if not query.endswith(";"):
            query += ";"

        # Inject area into user query
        query = self._inject_area(query)

        if self.debug:
            print(query)

        if self.responseformat == "geojson":
            template = self._GEOJSON_QUERY_TEMPLATE
            query = template.format(query=query)
        else:
            template = self._QUERY_TEMPLATE
            query = template.format(query=query, out=self.responseformat)

        if self.debug:
            print(query)
        return query

    def _GetFromOverpass(self, query):
        """This sends the API request to the Overpass instance and
        returns the raw result, or an error."""

        payload = {"data": query}

        try:
            r = requests.post(
                self.endpoint,
                data=payload,
                timeout=self.timeout,
                headers={'Accept-Charset': 'utf-8;q=0.7,*;q=0.7'}
            )

        except requests.exceptions.Timeout:
            raise TimeoutError(self._timeout)

        self._status = r.status_code

        if self._status != 200:
            if self._status == 400:
                raise OverpassSyntaxError(query)
            elif self._status == 429:
                raise MultipleRequestsError()
            elif self._status == 504:
                raise ServerLoadError(self._timeout)
            raise UnknownOverpassError(
                "The request returned status code {code}".format(
                    code=self._status
                    )
                )
        else:
            r.encoding = 'utf-8'
            return r.text

    def _asGeoJSON(self, elements):

        features = []
        for elem in elements:
            elem_type = elem["type"]
            if elem_type == "node":
                geometry = geojson.Point((elem["lon"], elem["lat"]))
            elif elem_type == "way":
                points = []
                for coords in elem["geometry"]:
                    points.append((coords["lon"], coords["lat"]))
                geometry = geojson.LineString(points)
            else:
                continue

            feature = geojson.Feature(
                id=elem["id"],
                geometry=geometry,
                properties=elem.get("tags"))
            features.append(feature)

        return geojson.FeatureCollection(features)

    def _toAreaId(self, nominatim_response):
        """Converts an OSM id to an Overpass Area ID according to 
        http://wiki.openstreetmap.org/wiki/Overpass_API/Overpass_QL#By_area_.28area.29"""

        WAY_MODIFIER = 2400000000
        RELATION_MODIFIER = 3600000000
        if nominatim_response.get('osm_type') and nominatim_response.get('osm_id'):
            if nominatim_response.get('osm_type') == "way":
                return int(nominatim_response.get('osm_id')) + WAY_MODIFIER
            elif nominatim_response.get('osm_type') == "relation":
                return int(nominatim_response.get('osm_id')) + RELATION_MODIFIER
        else:
            return NominatimError("Nominatim lookup did not return a way or relation with confidence")

    def _inject_area(self, query):
        """injects defined area id into user query"""

        import re

        # If no area ID is defined, just pass through
        if not self.area_id:
            return query

        if self.debug:
            print("before inject: ", query)

        return re.sub(
            r'((node|way|relation)[^;]*)',
            r'\1(area:{area_id})'.format(area_id=self.area_id),
            query)