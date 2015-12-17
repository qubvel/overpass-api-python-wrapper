import overpass

TEST_AREA_NAME = "Rhode Island"
TEST_AREA_ID = 3600000000 + 392915

def test_initialize_api():
    api = overpass.API()
    assert isinstance(api, overpass.API)
    assert api.debug is False

def test_construct_query_1():
    api = overpass.API()
    api.query = 'node[shop=retail]'
    assert api.raw_query == '[out:json];node[shop=retail];out body geom;'

def test_construct_query_2():
    api = overpass.API(responseformat='xml')
    api.query = 'node[shop=retail]'
    assert api.raw_query == '[out:xml];node[shop=retail];out body;'

def test_construct_query_3():
    api = overpass.API(responseformat='json')
    api.query = 'node[shop=retail]'
    assert api.raw_query == '[out:json];node[shop=retail];out body;'

def test_construct_query_area_1():
    api = overpass.API()
    api.area = TEST_AREA_NAME
    api.query = 'node[shop=retail]'
    assert api.raw_query == '[out:json];node[shop=retail](area:{area_id});out body geom;'.format(area_id=TEST_AREA_ID)

def test_construct_query_area_1():
    api = overpass.API()
    api.area = TEST_AREA_NAME
    api.query = 'node["type"="restriction"];way["type"="restriction"];relation["type"="restriction"];out body;>;'
    assert api.raw_query == '[out:json];node["type"="restriction"](area:{area_id});way["type"="restriction"](area:{area_id});relation["type"="restriction"](area:{area_id});out body;>;out body geom;'.format(area_id=TEST_AREA_ID)

def test_nominatim_lookup():
	api = overpass.API()
	api.area = TEST_AREA_NAME
	assert api.area_id == TEST_AREA_ID

def test_geojson():
    api = overpass.API()
    osm_geo = api.Get(
        overpass.MapQuery(41.73007, -71.58598, 41.73599, -71.57661))
    assert len(osm_geo['features']) > 1