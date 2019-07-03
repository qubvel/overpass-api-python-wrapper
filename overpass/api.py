# Copyright 2015-2018 Martijn van Exel.
# This file is part of the overpass-api-python-wrapper project
# which is licensed under Apache 2.0.
# See LICENSE.txt for the full license text.

import requests
import json
import csv
import geojson
import logging
from io import StringIO
from .errors import (
    OverpassSyntaxError,
    TimeoutError,
    MultipleRequestsError,
    ServerLoadError,
    UnknownOverpassError,
    ServerRuntimeError,
)


class API(object):
    """A simple Python wrapper for the OpenStreetMap Overpass API."""

    SUPPORTED_FORMATS = ["geojson", "json", "xml", "csv"]

    # defaults for the API class
    _timeout = 25  # second
    _endpoint = "https://overpass-api.de/api/interpreter"
    _headers = {"Accept-Charset": "utf-8;q=0.7,*;q=0.7"}
    _debug = False
    _proxies = None

    _QUERY_TEMPLATE = "[out:{out}];{query}out {verbosity};"
    _GEOJSON_QUERY_TEMPLATE = "[out:json];{query}out {verbosity};"

    def __init__(self, *args, **kwargs):
        self.endpoint = kwargs.get("endpoint", self._endpoint)
        self.headers = kwargs.get("headers", self._headers)
        self.timeout = kwargs.get("timeout", self._timeout)
        self.debug = kwargs.get("debug", self._debug)
        self.proxies = kwargs.get("proxies", self._proxies)
        self._status = None

        if self.debug:
            # https://stackoverflow.com/a/16630836
            try:
                import http.client as http_client
            except ImportError:
                # Python 2
                import httplib as http_client
            http_client.HTTPConnection.debuglevel = 1

            # You must initialize logging,
            # otherwise you'll not see debug output.
            logging.basicConfig()
            logging.getLogger().setLevel(logging.DEBUG)
            requests_log = logging.getLogger("requests.packages.urllib3")
            requests_log.setLevel(logging.DEBUG)
            requests_log.propagate = True

    def get(self, query, responseformat="geojson", verbosity="body", build=True):
        """Pass in an Overpass query in Overpass QL."""
        # Construct full Overpass query
        if build:
            full_query = self._construct_ql_query(
                query, responseformat=responseformat, verbosity=verbosity
            )
        else:
            full_query = query

        if self.debug:
            logging.getLogger().info(query)

        # Get the response from Overpass
        r = self._get_from_overpass(full_query)
        content_type = r.headers.get("content-type")

        if self.debug:
            print(content_type)
        if content_type == "text/csv":
            result = []
            reader = csv.reader(StringIO(r.text), delimiter="\t")
            for row in reader:
                result.append(row)
            return result
        elif content_type in ("text/xml", "application/xml", "application/osm3s+xml"):
            return r.text
        elif content_type == "application/json":
            response = json.loads(r.text)

        if not build:
            return response

        # Check for valid answer from Overpass.
        # A valid answer contains an 'elements' key at the root level.
        if "elements" not in response:
            raise UnknownOverpassError("Received an invalid answer from Overpass.")

        # If there is a 'remark' key, it spells trouble.
        overpass_remark = response.get("remark", None)
        if overpass_remark and overpass_remark.startswith("runtime error"):
            raise ServerRuntimeError(overpass_remark)

        if responseformat is not "geojson":
            return response

        # construct geojson
        return self._as_geojson(response["elements"])

    def search(self, feature_type, regex=False):
        """Search for something."""
        raise NotImplementedError()

    # deprecation of upper case functions
    Get = get
    Search = search

    def _construct_ql_query(self, userquery, responseformat, verbosity):
        raw_query = str(userquery).rstrip()
        if not raw_query.endswith(";"):
            raw_query += ";"

        if responseformat == "geojson":
            template = self._GEOJSON_QUERY_TEMPLATE
            complete_query = template.format(query=raw_query, verbosity=verbosity)
        else:
            template = self._QUERY_TEMPLATE
            complete_query = template.format(
                query=raw_query, out=responseformat, verbosity=verbosity
            )

        if self.debug:
            print(complete_query)
        return complete_query

    def _get_from_overpass(self, query):
        payload = {"data": query}

        try:
            r = requests.post(
                self.endpoint,
                data=payload,
                timeout=self.timeout,
                proxies=self.proxies,
                headers=self.headers,
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
                "The request returned status code {code}".format(code=self._status)
            )
        else:
            r.encoding = "utf-8"
            return r

    def _as_geojson(self, elements):

        features = []
        no_match_count = 0
        for elem in elements:
            elem_type = elem["type"]
            if elem_type == "node":
                geometry = geojson.Point((elem["lon"], elem["lat"]))
                feature = geojson.Feature(
                    id=elem["id"],
                    geometry=geometry,
                    properties=elem.get("tags"))
                features.append(feature)

            elif elem_type == "way":
                points = []
                for coords in elem["geometry"]:
                    points.append((coords["lon"], coords["lat"]))
                geometry = geojson.LineString(points)
                feature = geojson.Feature(
                    id=elem["id"],
                    geometry=geometry,
                    properties=elem.get("tags"))
                features.append(feature)

            elif elem_type == "relation":
                # initialize result lists
                polygons = []
                poly = []
                points = []
                # conditions
                prev = "inner"
                not_first = False

                for pos in range(len(elem["members"])):
                    mem = elem['members'][pos]

                    # check whether the coordinates of the next member need to be reversed
                    # also sometimes the next member may not actually connect to the previous member,
                    # so if necessary, find a matching member
                    if points:
                        dist_start = (points[-1][0] - mem["geometry"][0]["lon"]) ** 2 + (
                                points[-1][1] - mem["geometry"][0]["lat"]) ** 2
                        dist_end = (points[-1][0] - mem["geometry"][-1]["lon"]) ** 2 + (
                                points[-1][1] - mem["geometry"][-1]["lat"]) ** 2
                        if dist_start == 0:
                            pass  # don't need to do anything
                        elif dist_end == 0:
                            # flip the next member - it is entered in the wrong direction
                            mem["geometry"] = list(reversed(mem["geometry"]))
                        else:
                            # try flipping the previous member
                            dist_flipped_start = (points[0][0] - mem["geometry"][0]["lon"]) ** 2 + (
                                    points[0][1] - mem["geometry"][0]["lat"]) ** 2
                            dist_flipped_end = (points[0][0] - mem["geometry"][-1]["lon"]) ** 2 + (
                                    points[0][1] - mem["geometry"][-1]["lat"]) ** 2
                            if dist_flipped_start == 0:
                                # just flip the start
                                points = list(reversed(points))
                            elif dist_flipped_end == 0:
                                # both need to be flipped
                                points = list(reversed(points))
                                mem["geometry"] = list(reversed(mem["geometry"]))
                            else:
                                # no matches -- look for a new match
                                point_found = False
                                for i in range(pos + 1, len(elem['members'])):
                                    if not point_found:
                                        new_pt = elem['members'][i]
                                        dist_start = (new_pt['geometry'][0]['lon'] - points[-1][0]) ** 2 + (
                                                new_pt['geometry'][0]['lat'] - points[-1][1]) ** 2
                                        dist_end = (new_pt['geometry'][-1]['lon'] - points[-1][0]) ** 2 + (
                                                new_pt['geometry'][-1]['lat'] - points[-1][1]) ** 2

                                        if dist_start == 0 or dist_end == 0:
                                            point_found = True
                                            # swap the order of the members -- we have found the one we want
                                            elem['members'][pos], elem['members'][i] = (
                                                elem['members'][i],
                                                elem['members'][pos],
                                            )
                                            # save this new point as mem
                                            mem = elem['members'][pos]

                                            if dist_end == 0:
                                                mem['geometry'] = list(reversed(mem['geometry']))

                                if not point_found:
                                    no_match_count += 1
                                    # don't work with this park
                                    continue

                    # address outer values
                    if mem['role'] == 'outer':
                        if prev == "inner":
                            # start new outer polygon
                            points = []

                        if points == [] and not_first:
                            # append the previous poly to the polygon list
                            polygons.append(poly)
                            poly = []

                        for coords in mem["geometry"]:
                            try:
                                points.append([coords["lon"], coords["lat"]])
                            except Exception as e:
                                logging.getLogger().exception(e)

                        if points[-1] == points[0]:
                            # finish the outer polygon if it has met the start
                            poly.append(points)
                            points = []
                        # update condition
                        prev = "outer"

                    # address inner points
                    if mem['role'] == "inner":
                        for coords in mem["geometry"]:
                            points.append([coords["lon"], coords["lat"]])

                        # check if the inner is complete
                        if points[-1] == points[0]:
                            poly.append(points)
                            points = []
                        # update conditoin
                        prev = "inner"

                    not_first = True

                # add in the final poly
                polygons.append(poly)

                if polygons != [[]]:
                    # create MultiPolygon feature - separate multipolygon for each outer
                    for outer_poly in polygons:
                        poly_props = elem.get("tags")
                        poly_props.update({'id': elem['id']})
                        multipoly = {"type": "Feature",
                                     "properties": poly_props,
                                     "geometry": {
                                         "type": "MultiPolygon",
                                         "coordinates": [outer_poly]}}

                        # add to features
                        features.append(multipoly)

        return geojson.FeatureCollection(features)
