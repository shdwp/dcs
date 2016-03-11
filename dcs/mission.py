import zipfile
import sys
import os
import tempfile
from typing import List, Dict, Union, Optional
from datetime import datetime
from . import lua
from . import unitgroup
from . import unittype
from .country import Country
from . import countries
from .point import Point, MovingPoint
from .vehicle import Vehicle
from .ship import Ship
from .plane import Plane, PlaneType
from .helicopter import Helicopter, HelicopterType
from .static import Static
from .translation import Translation
from .terrain import Terrain, Caucasus, Nevada, ParkingSlot, Airport
from .goals import Goals
from . import mapping
from . import planes
from . import helicopters
from . import task
from . import weather
from .groundcontrol import GroundControl


class Options:
    def __init__(self):
        self.options = {}

    def load_from_dict(self, d):
        self.options = d

    def __str__(self):
        return lua.dumps(self.options, "options", 1)

    def __repr__(self):
        return repr(self.options)


class Warehouses:
    def __init__(self, terrain: Terrain):
        self.terrain = terrain
        self.warehouses = {}

    def load_dict(self, data):
        for x in data.get("airports", {}):
            self.terrain.airport_by_id(x).load_from_dict(data["airports"][x])

    def __str__(self):
        airports = self.terrain.airports
        d = {
            "warehouses": self.warehouses,
            "airports": {airports[x].id: airports[x].dict() for x in airports}
        }
        return lua.dumps(d, "warehouses", 1)


class MapPosition:
    def __init__(self, x, y):
        self._x = x
        self._y = y

    def x(self):
        return self._x

    def y(self):
        return self._y


class Coalition:
    def __init__(self, name, bullseye=None):
        self.name = name
        self.countries = {}  # type: Dict[str, Country]
        self.bullseye = bullseye
        self.nav_points = []  # TODO

    def set_bullseye(self, bulls):
        self.bullseye = bulls

    def add_country(self, country):
        self.countries[country.name] = country
        return country

    def remove_country(self, name):
        return self.countries.pop(name)

    def swap_country(self, coalition, name):
        return coalition.add_country(self.remove_country(name))

    def country(self, country_name: str):
        return self.countries.get(country_name, None)

    def find_group(self, group_name, search="exact"):
        for c in self.countries:
            g = self.countries[c].find_group(group_name, search)
            if g:
                return g

        return None

    def dict(self):
        d = {"name": self.name}
        if self.bullseye:
            d["bullseye"] = self.bullseye
        d["country"] = {}
        i = 1
        for country in sorted(self.countries.keys()):
            d["country"][i] = self.country(country).dict()
            i += 1
        d["nav_points"] = {}
        return d


class TriggerZone:
    def __init__(self, _id, x=0, y=0, radius=1500, hidden=False, name=""):
        self.id = _id
        self.radius = radius
        self.x = x
        self.y = y
        self.hidden = hidden
        self.name = name
        self.color = {1: 1, 2: 1, 3: 1, 4: 0.15}

    def dict(self):
        return {
            "name": self.name,
            "hidden": self.hidden,
            "x": self.x,
            "y": self.y,
            "zoneId": self.id,
            "radius": self.radius,
            "color": self.color
        }


class Triggers:
    def __init__(self):
        self.current_zone_id = 0
        self.zones = []  # type: List[TriggerZone]

    def load_from_dict(self, data):
        self.current_zone_id = 0
        self.zones = []
        for x in data["zones"]:
            imp_zone = data["zones"][x]
            tz = TriggerZone(
                imp_zone["zoneId"],
                imp_zone["x"],
                imp_zone["y"],
                imp_zone["radius"],
                imp_zone["hidden"],
                imp_zone["name"]
            )
            tz.color = imp_zone["color"]
            self.zones.append(tz)
            self.current_zone_id = max(self.current_zone_id, tz.id)

    def triggerzone(self, x=0, y=0, radius=1500, hidden=False, name="") -> TriggerZone:
        self.current_zone_id += 1
        return TriggerZone(self.current_zone_id, x, y, radius, hidden, name)

    def dict(self):
        return {
            "zones": {i + 1: self.zones[i].dict() for i in range(0, len(self.zones))}
        }


class Mission:
    COUNTRY_IDS = {x for x in range(0, 13)} | {x for x in range(15, 47)}

    def __init__(self, terrain: Union[Caucasus, Nevada]=Caucasus()):
        self.current_unit_id = 0
        self.current_group_id = 0
        self.current_dict_id = 0
        self.filename = None

        self.translation = Translation(self)
        self.map_resource = MapResource(self)

        self._description_text = self.string("dcs mission")
        self._description_bluetask = self.string("blue task")
        self._description_redtask = self.string("red task")
        self.sortie = self.string("sortie text")
        self.pictureFileNameR = []
        self.pictureFileNameB = []
        self.version = 11
        self.currentKey = 0
        self.start_time = datetime.fromtimestamp(13039200 + 43200)
        self.terrain = terrain
        self.trigrules = {}
        self.triggers = Triggers()
        self.options = Options()
        self.warehouses = Warehouses(self.terrain)
        self.goals = Goals()
        blue = Coalition("blue")
        blue.add_country(countries.Australia())
        blue.add_country(countries.Belgium())
        blue.add_country(countries.Canada())
        blue.add_country(countries.Croatia())
        blue.add_country(countries.CzechRepublic())
        blue.add_country(countries.Denmark())
        blue.add_country(countries.France())
        blue.add_country(countries.Georgia())
        blue.add_country(countries.Germany())
        blue.add_country(countries.Israel())
        blue.add_country(countries.Italy())
        blue.add_country(countries.Norway())
        blue.add_country(countries.Poland())
        blue.add_country(countries.SouthKorea())
        blue.add_country(countries.Spain())
        blue.add_country(countries.TheNetherlands())
        blue.add_country(countries.UK())
        blue.add_country(countries.USA())
        blue.add_country(countries.Turkey())

        red = Coalition("red")
        red.add_country(countries.Abkhazia())
        red.add_country(countries.Belarus())
        red.add_country(countries.China())
        red.add_country(countries.Iran())
        red.add_country(countries.Kazakhstan())
        red.add_country(countries.NorthKorea())
        red.add_country(countries.Russia())
        red.add_country(countries.Serbia())
        red.add_country(countries.SouthOssetia())
        red.add_country(countries.Syria())
        red.add_country(countries.Ukraine())

        blue.bullseye = terrain.bullseye_blue
        red.bullseye = terrain.bullseye_red

        self.coalition = {"blue": blue, "red": red}  # type: Dict[str, Coalition]

        self.map = {
            "zoom": 1000000,
            "centerY": 680571.42857143,
            "centerX": -255714.28571428
        }

        self.failures = {}
        self.trig = {}
        self.groundControl = GroundControl()
        self.forcedOptions = {}
        self.resourceCounter = {}  # keep default or empty, old format
        self.needModules = {}
        self.weather = weather.Weather()
        self.usedModules = {
            'Su-25A by Eagle Dynamics': True,
            'MiG-21Bis AI by Leatherneck Simulations': True,
            'UH-1H Huey by Belsimtek': True,
            'Su-25T by Eagle Dynamics': True,
            'F-86F Sabre by Belsimtek': True,
            'Su-27 Flanker by Eagle Dynamics': True,
            'Hawk T.1A AI by VEAO Simulations': True,
            'MiG-15bis AI by Eagle Dynamics': True,
            'Ka-50 Black Shark by Eagle Dynamics': True,
            'Combined Arms by Eagle Dynamics': True,
            'L-39C/ZA by Eagle Dynamics': True,
            'A-10C Warthog by Eagle Dynamics': True,
            'F-5E/E-3 by Belsimtek': True,
            'C-101 Aviojet': True,
            'TF-51D Mustang by Eagle Dynamics': True,
            './CoreMods/aircraft/MQ-9 Reaper': True,
            'C-101 Aviojet by AvioDev': True,
            'P-51D Mustang by Eagle Dynamics': True,
            'A-10A by Eagle Dynamics': True,
            'L-39C': True,
            'World War II AI Units by Eagle Dynamics': True,
            'MiG-15bis by Belsimtek': True,
            'F-15C': True,
            'Flaming Cliffs by Eagle Dynamics': True,
            'Bf 109 K-4 by Eagle Dynamics': True,
            'Mi-8MTV2 Hip by Belsimtek': True,
            'MiG-21Bis by Leatherneck Simulations': True,
            'M-2000C by RAZBAM Sims': True,
            'M-2000C AI by RAZBAM Sims': True,
            'FW-190D9 Dora by Eagle Dynamics': True,
            'Caucasus': True,
            'Hawk T.1A by VEAO Simulations': True,
            'F-86F Sabre AI by Eagle Dynamics': True
        }

    def _import_moving_point(self, group: unitgroup.Group, imp_group) -> unitgroup.Group:
        for imp_point_idx in imp_group["route"]["points"]:
            imp_point = imp_group["route"]["points"][imp_point_idx]
            point = MovingPoint()
            point.load_from_dict(imp_point, self.translation)
            group.add_point(point)
        return group

    def _import_static_point(self, group: unitgroup.Group, imp_group) -> unitgroup.Group:
        for imp_point_idx in imp_group["route"]["points"]:
            imp_point = imp_group["route"]["points"][imp_point_idx]
            point = Point()
            point.load_from_dict(imp_point, self.translation)
            group.add_point(point)
        return group

    def _imp_coalition(self, coalition, key):
        if key not in coalition:
            return None
        imp_col = coalition[key]
        col = Coalition(key, imp_col["bullseye"])
        for country_idx in imp_col["country"]:
            imp_country = imp_col["country"][country_idx]
            _country = countries.get_by_id(imp_country["id"])

            if "vehicle" in imp_country:
                for vgroup_idx in imp_country["vehicle"]["group"]:
                    vgroup = imp_country["vehicle"]["group"][vgroup_idx]
                    vg = unitgroup.VehicleGroup(vgroup["groupId"], self.translation.get_string(vgroup["name"]),
                                                vgroup["start_time"])
                    vg.load_from_dict(vgroup)
                    self.current_group_id = max(self.current_group_id, vg.id)

                    self._import_moving_point(vg, vgroup)

                    # units
                    for imp_unit_idx in vgroup["units"]:
                        imp_unit = vgroup["units"][imp_unit_idx]
                        unit = Vehicle(
                            id=imp_unit["unitId"],
                            name=self.translation.get_string(imp_unit["name"]),
                            _type=imp_unit["type"])
                        unit.load_from_dict(imp_unit)

                        self.current_unit_id = max(self.current_unit_id, unit.id)
                        vg.add_unit(unit)
                    _country.add_vehicle_group(vg)

            if "ship" in imp_country:
                for group_idx in imp_country["ship"]["group"]:
                    imp_group = imp_country["ship"]["group"][group_idx]
                    vg = unitgroup.ShipGroup(imp_group["groupId"], self.translation.get_string(imp_group["name"]),
                                             imp_group["start_time"])
                    vg.load_from_dict(imp_group)
                    self.current_group_id = max(self.current_group_id, vg.id)

                    self._import_moving_point(vg, imp_group)

                    # units
                    for imp_unit_idx in imp_group["units"]:
                        imp_unit = imp_group["units"][imp_unit_idx]
                        unit = Ship(
                            id=imp_unit["unitId"],
                            name=self.translation.get_string(imp_unit["name"]),
                            _type=imp_unit["type"])
                        unit.load_from_dict(imp_unit)

                        self.current_unit_id = max(self.current_unit_id, unit.id)
                        vg.add_unit(unit)
                    _country.add_ship_group(vg)

            if "plane" in imp_country:
                for pgroup_idx in imp_country["plane"]["group"]:
                    pgroup = imp_country["plane"]["group"][pgroup_idx]
                    plane_group = unitgroup.PlaneGroup(pgroup["groupId"], self.translation.get_string(pgroup["name"]),
                                                       pgroup["start_time"])
                    plane_group.load_from_dict(pgroup)
                    self.current_group_id = max(self.current_group_id, plane_group.id)

                    self._import_moving_point(plane_group, pgroup)

                    # units
                    for imp_unit_idx in pgroup["units"]:
                        imp_unit = pgroup["units"][imp_unit_idx]
                        plane = Plane(
                            _id=imp_unit["unitId"],
                            name=self.translation.get_string(imp_unit["name"]),
                            _type=planes.plane_map[imp_unit["type"]])
                        plane.load_from_dict(imp_unit)

                        self.current_unit_id = max(self.current_unit_id, plane.id)
                        plane_group.add_unit(plane)
                    _country.add_plane_group(plane_group)

            if "helicopter" in imp_country:
                for pgroup_idx in imp_country["helicopter"]["group"]:
                    pgroup = imp_country["helicopter"]["group"][pgroup_idx]
                    helicopter_group = unitgroup.HelicopterGroup(
                        pgroup["groupId"],
                        self.translation.get_string(pgroup["name"]),
                        pgroup["start_time"])
                    helicopter_group.load_from_dict(pgroup)
                    self.current_group_id = max(self.current_group_id, helicopter_group.id)

                    self._import_moving_point(helicopter_group, pgroup)

                    # units
                    for imp_unit_idx in pgroup["units"]:
                        imp_unit = pgroup["units"][imp_unit_idx]
                        heli = Helicopter(
                            _id=imp_unit["unitId"],
                            name=self.translation.get_string(imp_unit["name"]),
                            _type=helicopters.helicopter_map[imp_unit["type"]])
                        heli.load_from_dict(imp_unit)

                        self.current_unit_id = max(self.current_unit_id, heli.id)
                        helicopter_group.add_unit(heli)
                    _country.add_helicopter_group(helicopter_group)

            if "static" in imp_country:
                for sgroup_idx in imp_country["static"]["group"]:
                    sgroup = imp_country["static"]["group"][sgroup_idx]
                    static_group = unitgroup.StaticGroup(sgroup["groupId"], self.translation.get_string(sgroup["name"]))
                    static_group.load_from_dict(sgroup)
                    self.current_group_id = max(self.current_group_id, static_group.id)

                    self._import_static_point(static_group, sgroup)

                    # units
                    for imp_unit_idx in sgroup["units"]:
                        imp_unit = sgroup["units"][imp_unit_idx]
                        static = Static(
                            id=imp_unit["unitId"],
                            name=self.translation.get_string(imp_unit["name"]),
                            _type=imp_unit["type"])
                        static.load_from_dict(imp_unit)

                        self.current_unit_id = max(self.current_unit_id, static.id)
                        static_group.add_unit(static)
                    _country.add_static_group(static_group)
            col.add_country(_country)
        return col

    def load_file(self, filename):
        self.filename = filename
        mission_dict = {}
        options_dict = {}
        warehouse_dict = {}
        dictionary_dict = {}

        def loaddict(fname, mizfile):
            with mizfile.open(fname) as mfile:
                data = mfile.read()
                data = data.decode()
                return lua.loads(data)

        with zipfile.ZipFile(filename, 'r') as miz:
            mission_dict = loaddict('mission', miz)
            if mission_dict["mission"]["version"] < 9:
                print("Mission file is using an old format, be aware!", file=sys.stderr)
            options_dict = loaddict('options', miz)
            warehouse_dict = loaddict('warehouses', miz)
            dictionary_dict = loaddict('l10n/DEFAULT/dictionary', miz)
            if 'l10n/DEFAULT/mapResource' in miz.namelist():
                mapresource_dict = loaddict('l10n/DEFAULT/mapResource', miz)
                self.map_resource.load_from_dict(mapresource_dict, miz)

        imp_mission = mission_dict["mission"]

        # import translations
        self.translation = Translation(self)
        translation_dict = dictionary_dict["dictionary"]
        for sid in translation_dict:
            self.translation.set_string(sid, translation_dict[sid], 'DEFAULT')

        self.current_dict_id = imp_mission["maxDictId"]

        # print(self.translation)

        # setup terrain
        if imp_mission["theatre"] == 'Caucasus':
            self.terrain = Caucasus()
        elif imp_mission["theatre"] == 'Nevada':
            self.terrain = Nevada()
        else:
            raise RuntimeError("Unknown theatre: '{theatre}'".format(theatre=imp_mission["theatre"]))

        # import options
        self.options = Options()
        self.options.load_from_dict(options_dict["options"])

        # import warehouses
        self.warehouses = Warehouses(self.terrain)
        self.warehouses.load_dict(warehouse_dict["warehouses"])

        # import base values
        self._description_text = self.translation.get_string(imp_mission["descriptionText"])
        self._description_bluetask = self.translation.get_string(imp_mission["descriptionBlueTask"])
        self._description_redtask = self.translation.get_string(imp_mission["descriptionRedTask"])
        self.sortie = self.translation.get_string(imp_mission["sortie"])
        for pic in sorted(imp_mission["pictureFileNameR"]):
            self.pictureFileNameR.append(imp_mission["pictureFileNameR"][pic])
        for pic in sorted(imp_mission["pictureFileNameB"]):
            self.pictureFileNameB.append(imp_mission["pictureFileNameB"][pic])
        self.version = imp_mission["version"]
        self.currentKey = imp_mission["currentKey"]
        self.start_time = datetime.fromtimestamp(13039200 + imp_mission["start_time"])
        self.usedModules = imp_mission["usedModules"]
        self.needModules = imp_mission["needModules"]

        # groundControl
        self.groundControl = GroundControl()
        self.groundControl.load_from_dict(imp_mission.get("groundControl"))

        # goals
        self.goals = Goals()
        self.goals.load_from_dict(imp_mission["goals"])

        # trig
        self.trig = imp_mission["trig"]  # TODO

        # triggers
        self.triggers = Triggers()
        self.triggers.load_from_dict(imp_mission["triggers"])

        # trigrules
        self.trigrules = imp_mission["trigrules"]  # TODO

        # failures
        self.failures = imp_mission["failures"]  # TODO

        # forced options
        self.forcedOptions = imp_mission["forcedOptions"]  # TODO

        # map
        self.map = imp_mission["map"]

        # weather
        imp_weather = imp_mission["weather"]
        self.weather = weather.Weather()
        self.weather.load_from_dict(imp_weather)

        # import coalition with countries and units
        self.coalition["blue"] = self._imp_coalition(imp_mission["coalition"], "blue")
        self.coalition["red"] = self._imp_coalition(imp_mission["coalition"], "red")
        neutral_col = self._imp_coalition(imp_mission["coalition"], "neutral")
        if neutral_col:
            self.coalition["neutral"] = neutral_col

        return True

    def description_text(self):
        return str(self._description_text)

    def set_description_text(self, text):
        self._description_text.set(text)

    def description_bluetask_text(self):
        return str(self._description_bluetask)

    def set_description_bluetask_text(self, text):
        self._description_bluetask.set(text)

    def description_redtask_text(self):
        return str(self._description_redtask)

    def set_description_redtask_text(self, text):
        self._description_redtask.set(text)

    def add_picture_red(self, filepath):
        self.pictureFileNameR.append(self.map_resource.add_resource_file(filepath))

    def add_picture_blue(self, filepath):
        self.pictureFileNameB.append(self.map_resource.add_resource_file(filepath))

    def next_group_id(self):
        self.current_group_id += 1
        return self.current_group_id

    def next_unit_id(self):
        self.current_unit_id += 1
        return self.current_unit_id

    def next_dict_id(self):
        self.current_dict_id += 1
        return self.current_dict_id

    def string(self, s, lang='DEFAULT'):
        """
        Create a new String() object for translation
        :param s: string for lang
        :param lang: language for s
        :return: A new String() object for string s
        """
        return self.translation.create_string(s, lang)

    def vehicle(self, name, _type: unittype.VehicleType):
        if not issubclass(_type, unittype.VehicleType):
            raise TypeError("_type not a unittype.VehicleType class: " + repr(_type))
        return Vehicle(self.next_unit_id(), self.string(name), _type.id)

    def vehicle_group(self, _country, name, _type: unittype.VehicleType, x, y, heading=0, group_size=1, action="Off Road",
                      formation=unitgroup.VehicleGroup.Formation.Line) -> unitgroup.VehicleGroup:
        vg = unitgroup.VehicleGroup(self.next_group_id(), self.string(name))

        for i in range(1, group_size + 1):
            v = self.vehicle(name + " Unit #{nr}".format(nr=i), _type)
            v.x = x
            v.y = y + (i - 1) * 20
            v.heading = heading
            vg.add_unit(v)

        wp = vg.add_waypoint(vg.units[0].x, vg.units[0].y, action, 0)
        wp.ETA_locked = True

        vg.formation(formation)

        _country.add_vehicle_group(vg)
        return vg

    def vehicle_group_platoon(self, _country, name, types: List[unittype.VehicleType], x, y, heading=0, action="Off Road",
                              formation=unitgroup.VehicleGroup.Formation.Line) -> unitgroup.VehicleGroup:
        vg = unitgroup.VehicleGroup(self.next_group_id(), self.string(name))

        for i in range(0, len(types)):
            utype = types[i]
            v = self.vehicle(name + " Unit #{nr}".format(nr=i + 1), utype)
            v.x = x
            v.y = y + i * 20
            v.heading = heading
            vg.add_unit(v)

        wp = vg.add_waypoint(vg.units[0].x, vg.units[0].y, action, 0)
        wp.ETA_locked = True

        vg.formation(formation)

        _country.add_vehicle_group(vg)
        return vg

    def ship(self, name, _type):
        return Ship(self.next_unit_id(), self.string(name), _type)

    def ship_group(self, _country, name, _type: str, x, y, heading=0, group_size=1) -> unitgroup.ShipGroup:
        sg = unitgroup.ShipGroup(self.next_group_id(), self.string(name))

        for i in range(1, group_size + 1):
            v = self.ship(name + " Unit #{nr}".format(nr=i), _type)
            v.x = x
            v.y = y + (i - 1) * 20
            v.heading = heading
            sg.add_unit(v)

        wp = sg.add_waypoint(x, y, 20)
        wp.ETA_locked = True

        _country.add_ship_group(sg)
        return sg

    def plane_group(self, name):
        return unitgroup.PlaneGroup(self.next_group_id(), self.string(name))

    def plane_group_inflight(self, _country, name, plane_type: PlaneType, x, y, altitude, speed=600,
                             maintask: task.MainTask = None, group_size=1):
        if maintask is None:
            maintask = plane_type.task_default

        pg = self.plane_group(name)
        pg.task = maintask.name
        group_size = min(group_size, plane_type.group_size_max)

        for i in range(1, group_size + 1):
            p = self.plane(name + " Pilot #{nr}".format(nr=i), plane_type)
            p.x = x
            p.y = y
            p.alt = altitude
            pg.add_unit(p)

        _country.add_plane_group(self._flying_group_inflight(_country, pg, maintask, altitude, speed))
        return pg

    def plane_group_from_runway(self, _country, name, plane_type: PlaneType, airport: Airport,
                                maintask: task.MainTask = None, group_size=1):
        if not airport.runway_free:
            raise RuntimeError("Runway already occupied.")

        airport.runway_free = False
        if maintask is None:
            maintask = plane_type.task_default

        pg = self.plane_group(name)
        pg.task = maintask.name
        group_size = min(group_size, plane_type.group_size_max)

        for i in range(1, group_size + 1):
            p = self.plane(name + " Pilot #{nr}".format(nr=i), plane_type)
            pg.add_unit(p)

        _country.add_plane_group(self._flying_group_runway(_country, pg, maintask, airport))
        return pg

    def plane_group_from_parking(self,
                                 _country: Country,
                                 name,
                                 plane_type: PlaneType,
                                 airport: Airport,
                                 maintask: task.MainTask = None,
                                 coldstart=True,
                                 parking_slots: ParkingSlot = None,
                                 group_size=1) -> unitgroup.PlaneGroup:
        """
        Add a new PlaneGroup at parking position on the given airport.
        :param _country: Country object the plane group belongs to
        :param name: Name of the plane group
        :param maintask: Task of the plane group
        :param plane_type: PlaneType object representing the plane
        :param airport: Airport object on which to spawn the plane
        :param coldstart: Coldstart yes or no
        :param parking_slots: List of parking slots to use for planes
        :param group_size: Group size 1-4
        :return: the new PlaneGroup
        """
        if maintask is None:
            maintask = plane_type.task_default

        pg = self.plane_group(name)
        pg.task = maintask.name
        group_size = min(group_size, plane_type.group_size_max)

        for i in range(1, group_size + 1):
            p = self.plane(name + " Pilot #{nr}".format(nr=i), plane_type)
            pg.add_unit(p)

        task_payload = plane_type.loadout(maintask)
        if task_payload:
            for p in pg.units:
                for x in task_payload:
                    p.load_pylon(x)

        _country.add_plane_group(self._flying_group_ramp(_country, pg, maintask, airport, coldstart, parking_slots))
        return pg

    def plane(self, name, _type: PlaneType):
        return Plane(self.next_unit_id(), self.string(name), _type)

    def helicopter(self, name, _type: HelicopterType):
        return Helicopter(self.next_unit_id(), self.string(name), _type)

    def helicopter_group(self, name):
        return unitgroup.HelicopterGroup(self.next_group_id(), self.string(name))

    @classmethod
    def _assign_callsign(cls, _country, group):
        callsign_name = None
        category = group.units[0].unit_type.category
        if category in _country.callsign:
            callsign_name = _country.next_callsign_category(category)

        i = 1
        for unit in group.units:
            if category in _country.callsign:
                unit.callsign_dict["name"] = callsign_name + str(1) + str(i)
                unit.callsign_dict[3] = i
            else:
                unit.callsign = _country.next_callsign_id()
            i += 1

    @staticmethod
    def _load_tasks(mp: MovingPoint, maintask: task.MainTask):
        for t in maintask.perform_task:
            ptask = t()
            ptask.auto = True
            mp.tasks.append(ptask)
        return mp

    def _flying_group_ramp(self, _country, group: unitgroup.FlyingGroup, maintask: task.MainTask, airport: Airport,
                           coldstart=True,
                           parking_slots: List[ParkingSlot] = None):

        i = 0
        for unit in group.units:
            parking_slot = parking_slots.pop(i) if parking_slots else airport.free_parking_slot(
                unit.unit_type.large_parking_slot, unit.unit_type.helicopter)
            if parking_slot is None:
                raise RuntimeError("No free parking slot at " + airport.name)
            unit.x = parking_slot.x
            unit.y = parking_slot.y
            unit.set_parking(parking_slot)
            i += 1

        group.load_task_default_loadout(maintask)

        self._assign_callsign(_country, group)

        mp = MovingPoint()
        mp.type = "TakeOffParking" if coldstart else "TakeOffParkingHot"
        mp.action = "From Parking Area" if coldstart else "From Parking Area Hot"
        mp.x = group.units[0].x
        mp.y = group.units[0].y
        mp.airdrome_id = airport.id
        mp.alt = group.units[0].alt
        Mission._load_tasks(mp, maintask)

        group.add_point(mp)

        return group

    def _flying_group_runway(self, _country, group: unitgroup.FlyingGroup, maintask: task.MainTask, airport: Airport):
        for unit in group.units:
            unit.x = airport.x
            unit.y = airport.y

        self._assign_callsign(_country, group)

        group.load_task_default_loadout(maintask)

        mp = MovingPoint()
        mp.type = "TakeOff"
        mp.action = "From Runway"
        mp.x = group.units[0].x
        mp.y = group.units[0].y
        mp.airdrome_id = airport.id
        mp.alt = group.units[0].alt
        Mission._load_tasks(mp, maintask)

        group.add_point(mp)

        return group

    def _flying_group_inflight(self, _country, group: unitgroup.FlyingGroup, maintask: task.MainTask, altitude, speed):

        i = 0
        for unit in group.units:
            unit.alt = altitude
            unit.x += i * 10
            unit.speed = speed / 3.6
            i += 1

        self._assign_callsign(_country, group)

        group.load_task_default_loadout(maintask)

        mp = MovingPoint()
        mp.type = "Turning Point"
        mp.action = mp.type
        mp.x = group.units[0].x
        mp.y = group.units[0].y
        mp.alt = altitude
        mp.speed = speed / 3.6

        Mission._load_tasks(mp, maintask)

        group.add_point(mp)

        return group

    def helicopter_group_inflight(self, _country, name, helicopter_type, x, y, altitude, speed=200,
                                  maintask: task.MainTask = None, group_size=1):
        if maintask is None:
            maintask = helicopter_type.task_default

        hg = self.helicopter_group(name)
        hg.task = maintask.name
        group_size = min(group_size, helicopter_type.group_size_max)

        for i in range(1, group_size + 1):
            p = self.helicopter(name + " Pilot #{nr}".format(nr=i), helicopter_type)
            p.x = x
            p.y = y
            hg.add_unit(p)

        _country.add_helicopter_group(self._flying_group_inflight(_country, hg, maintask, altitude, speed))
        return hg

    def helicopter_group_from_runway(self, _country, name, heli_type: HelicopterType, airport: Airport,
                                     maintask: task.MainTask = None, group_size=1):
        if maintask is None:
            maintask = heli_type.task_default

        hg = self.helicopter_group(name)
        hg.task = maintask.name
        group_size = min(group_size, heli_type.group_size_max)

        for i in range(1, group_size + 1):
            p = self.helicopter(name + " Pilot #{nr}".format(nr=i), heli_type)
            hg.add_unit(p)

        _country.add_helicopter_group(self._flying_group_runway(_country, hg, maintask, airport))
        return hg

    def helicopter_group_from_parking(self,
                                      _country: Country,
                                      name,
                                      heli_type: HelicopterType,
                                      airport: Airport,
                                      maintask: task.MainTask = None,
                                      coldstart=True,
                                      parking_slots: List[ParkingSlot] = None,
                                      group_size=1) -> unitgroup.PlaneGroup:
        """
        Add a new PlaneGroup at parking position on the given airport.
        :param _country: Country object the plane group belongs to
        :param name: Name of the helicopter group
        :param maintask: Task of the helicopter group
        :param heli_type: HelicopterType object representing the helicopter
        :param airport: Airport object on which to spawn the helicopter
        :param coldstart: Coldstart yes or no
        :param parking_slots: List of parking slots to use for helicopters
        :param group_size: Group size 1-4
        :return: the new PlaneGroup
        """
        if maintask is None:
            maintask = heli_type.task_default

        hg = self.helicopter_group(name)
        hg.task = maintask.name
        group_size = min(group_size, heli_type.group_size_max)

        for i in range(1, group_size + 1):
            p = self.helicopter(name + " Pilot #{nr}".format(nr=i), heli_type)
            hg.add_unit(p)

        _country.add_helicopter_group(
            self._flying_group_ramp(_country, hg, maintask, airport, coldstart, parking_slots))
        return hg

    def refuel_flight(self,
                      _country,
                      name: str,
                      plane_type: PlaneType,
                      airport: Optional[Airport],
                      x,
                      y,
                      race_distance=30 * 1000,
                      heading=90,
                      altitude=4500,
                      speed=407,
                      coldstart=True,
                      frequency=140,
                      tacanchannel="10X") -> unitgroup.PlaneGroup:
        if airport:
            tanker = self.plane_group_from_parking(_country, name, plane_type, airport, coldstart=coldstart)
            wp = tanker.add_runway_waypoint(airport)
        else:
            x2, y2 = mapping.point_from_heading(x, y, (heading + 180) % 360, 2000)
            tanker = self.plane_group_inflight(_country, name, plane_type, x2, y2, altitude, speed, task.Refueling)
            x2, y2 = mapping.point_from_heading(x, y, heading + 180, 1000)
            wp = tanker.add_waypoint(x2, y2, altitude, speed)

        wp.tasks.append(task.SetFrequencyCommand(frequency))

        if plane_type.tacan:
            channel = int(tacanchannel[:-1])
            modechannel = tacanchannel[-1]
            tanker.points[0].tasks.append(task.ActivateBeaconCommand(channel, modechannel))

        wp = tanker.add_waypoint(x, y, altitude, speed)
        wp.tasks.append(task.OrbitAction(altitude, speed, "Race-Track"))

        x2, y2 = mapping.point_from_heading(x, y, heading, race_distance)
        tanker.add_waypoint(x2, y2, altitude, speed)

        return tanker

    def awacs_flight(self,
                     _country,
                     name: str,
                     plane_type: PlaneType,
                     airport: Optional[Airport],
                     x,
                     y,
                     race_distance=30 * 1000,
                     heading=90,
                     altitude=4500,
                     speed=550,
                     coldstart=True,
                     frequency=140) -> unitgroup.PlaneGroup:
        if airport:
            awacs = self.plane_group_from_parking(_country, name, plane_type, airport, coldstart=coldstart)
            wp = awacs.add_runway_waypoint(airport)
        else:
            x2, y2 = mapping.point_from_heading(x, y, (heading + 180) % 360, 2000)
            awacs = self.plane_group_inflight(_country, name, plane_type, x2, y2, altitude, speed, task.AWACS)
            x2, y2 = mapping.point_from_heading(x, y, heading + 180, 1000)
            wp = awacs.add_waypoint(x2, y2, altitude, speed)

        wp.tasks.append(task.SetFrequencyCommand(frequency))

        wp = awacs.add_waypoint(x, y, altitude, speed)
        wp.tasks.append(task.OrbitAction(altitude, speed, task.OrbitAction.Pattern_RaceTrack))

        x2, y2 = mapping.point_from_heading(x, y, heading, race_distance)
        awacs.add_waypoint(x2, y2, altitude, speed)

        return awacs

    def escort_flight(self,
                      _country,
                      name: str,
                      escort_type: planes.PlaneType,
                      airport: Optional[Airport],
                      group_to_escort: unitgroup.FlyingGroup,
                      group_size=2):

        second_point_group = group_to_escort.points[1]
        if airport:
            eg = self.plane_group_from_parking(
                _country, name, escort_type, airport, task.Escort, group_size=group_size)
            eg.add_runway_waypoint(airport)
        else:
            eg = self.plane_group_inflight(
                _country, name, escort_type,
                group_to_escort.points[0].x - 10 * 1000,
                group_to_escort.points[0].y,
                second_point_group.alt + 200,
                maintask=task.Escort,
                group_size=group_size
            )

        eg.add_waypoint(second_point_group.x, second_point_group.y, second_point_group.alt)
        eg.points[0].tasks.clear()
        eg.points[0].tasks.append(task.EscortTaskAction(group_to_escort.id, lastwpt=len(group_to_escort.points)))

        return eg

    def patrol_flight(self,
                      _country,
                      name: str,
                      patrol_type: planes.PlaneType,
                      airport: Optional[Airport],
                      x1,
                      y1,
                      x2,
                      y2,
                      speed=600,
                      altitude=4000,
                      group_size=2):
        if airport:
            eg = self.plane_group_from_parking(
                _country, name, patrol_type, airport, maintask=task.CAP, group_size=group_size)
            eg.add_runway_waypoint(airport)
        else:
            eg = self.plane_group_inflight(
                _country, name, patrol_type,
                x1 - 10 * 1000,
                y1,
                altitude,
                maintask=task.CAP,
                group_size=group_size
            )

        wp = eg.add_waypoint(x1, y1, altitude, speed)
        wp.tasks.append(task.OrbitAction(altitude, speed, task.OrbitAction.Pattern_RaceTrack))
        eg.add_waypoint(x2, y2, altitude, speed)

        return eg

    def country(self, name):
        for k in self.coalition:
            c = self.coalition[k].country(name)
            if c:
                return c
        return None

    def find_group(self, group_name, search="exact"):
        for k in self.coalition:
            g = self.coalition[k].find_group(group_name, search)
            if g:
                return g
        return None

    def is_red(self, _country: Country):
        return _country.name in self.coalition["red"].countries

    def is_blue(self, _country: Country):
        return _country.name in self.coalition["blue"].countries

    def stats(self) -> Dict:
        d = {
            "red": {},
            "blue": {},
            "unit_count": 0,
            "count": 0
        }

        def count_group(field, group):
            d[col_name]["count"] += len(group)
            d[col_name][field]["count"] += len(group)
            for g in group:
                for u in g.units:
                    _unit = d[col_name][field]["units"].get(u.type, 0)
                    d[col_name][field]["units"][u.type] = _unit + 1
                    d[col_name]["unit_count"] += 1
            d[col_name][field]["unit_count"] = sum(d[col_name][field]["units"].values())

        for col_name in ["red", "blue"]:
            d[col_name]["unit_count"] = 0
            d[col_name]["count"] = 0
            col = self.coalition[col_name]
            d[col_name]["plane_groups"] = {"count": 0, "units": {}}
            d[col_name]["helicopter_groups"] = {"count": 0, "units": {}}
            d[col_name]["vehicle_groups"] = {"count": 0, "units": {}}
            d[col_name]["ship_groups"] = {"count": 0, "units": {}}
            for k, v in col.countries.items():
                count_group("plane_groups", v.plane_group)
                count_group("helicopter_groups", v.helicopter_group)
                count_group("vehicle_groups", v.vehicle_group)
                count_group("ship_groups", v.ship_group)
            d["unit_count"] += d[col_name]["unit_count"]
            d["count"] += d[col_name]["count"]

        # import pprint
        # pp = pprint.PrettyPrinter(indent=2)
        # pp.pprint(d)
        return d

    def reload(self):
        if self.filename:
            return self.load_file(self.filename)
        raise RuntimeError("Currently no file loaded to reload.")

    def save(self, filename=None, show_stats=False):
        filename = self.filename if filename is None else filename
        if not filename:
            raise RuntimeError("No filename given.")
        self.filename = filename  # store filename

        with zipfile.ZipFile(filename, 'w', compression=zipfile.ZIP_DEFLATED) as zipf:
            # options
            zipf.writestr('options', str(self.options))

            # warehouses
            zipf.writestr('warehouses', str(self.warehouses))

            # translation files
            dicttext = lua.dumps(self.translation.dict('DEFAULT'), "dictionary", 1)
            zipf.writestr('l10n/DEFAULT/dictionary', dicttext)

            mapresource = self.map_resource.store(zipf, 'DEFAULT')
            # print(mapresource)
            zipf.writestr('l10n/DEFAULT/mapResource', lua.dumps(mapresource, "mapResource", 1))

            zipf.writestr('mission', str(self))

        if show_stats:
            d = self.stats()
            print("Mission Statistics")
            print("-"*60)
            output = {"red": [], "blue": []}
            for x in ["Blue", "Red"]:
                low = x.lower()
                output[low].append("{group:<15s} groups units".format(group=x))
                output[low].append("{group:<15s} {gc:6d} {u:5d}".format(
                    group="Plane",
                    gc=d[low]["plane_groups"]["count"], u=d[low]["plane_groups"]["unit_count"]))
                output[low].append("{group:<15s} {gc:6d} {u:5d}".format(
                    group="Helicopter",
                    gc=d[low]["helicopter_groups"]["count"], u=d[low]["helicopter_groups"]["unit_count"]))
                output[low].append("{group:<15s} {gc:6d} {u:5d}".format(
                    group="Vehicle",
                    gc=d[low]["vehicle_groups"]["count"], u=d[low]["vehicle_groups"]["unit_count"]))
                output[low].append("{group:<15s} {gc:6d} {u:5d}".format(
                    group="Ship",
                    gc=d[low]["ship_groups"]["count"], u=d[low]["ship_groups"]["unit_count"]))
                output[low].append("-"*28)
                output[low].append("{group:<15s} {gc:6d} {u:5d}".format(group="Sum", gc=d[low]["count"], u=d[low]["unit_count"]))

            # merge tables
            for i in range(0, len(output["blue"])):
                print(output["blue"][i], "  ", output["red"][i])
            print("Total {g} groups with {u} units".format(g=d["count"], u=d["unit_count"]))
        return True

    def dict(self):
        m = {
            "trig": self.trig
        }
        m["groundControl"] = self.groundControl.dict()
        m["usedModules"] = self.usedModules
        m["resourceCounter"] = self.resourceCounter
        m["triggers"] = self.triggers.dict()
        m["weather"] = self.weather.dict()
        m["theatre"] = self.terrain.name
        m["needModules"] = self.needModules
        m["map"] = self.map
        m["descriptionText"] = self._description_text.id
        m["pictureFileNameR"] = {}
        for i in range(0, len(self.pictureFileNameR)):
            m["pictureFileNameR"][i + 1] = self.pictureFileNameR[i]
        m["pictureFileNameB"] = {}
        for i in range(0, len(self.pictureFileNameB)):
            m["pictureFileNameB"][i + 1] = self.pictureFileNameB[i]
        m["descriptionBlueTask"] = self._description_bluetask.id
        m["descriptionRedTask"] = self._description_redtask.id
        m["trigrules"] = self.trigrules
        m["coalition"] = {}
        for col in self.coalition.keys():
            m["coalition"][col] = self.coalition[col].dict()
        col_blue = {self.coalition["blue"].country(x).id for x in self.coalition["blue"].countries.keys()}
        col_red = {self.coalition["red"].country(x).id for x in self.coalition["red"].countries.keys()}
        col_neutral = list(Mission.COUNTRY_IDS - col_blue - col_red)
        col_blue = list(col_blue)
        col_red = list(col_red)
        m["coalitions"] = {
            "neutral": {x + 1: col_neutral[x] for x in range(0, len(col_neutral))},
            "blue": {x + 1: col_blue[x] for x in range(0, len(col_blue))},
            "red": {x + 1: col_red[x] for x in range(0, len(col_red))}
        }
        m["sortie"] = self.sortie.id
        m["version"] = self.version
        m["goals"] = self.goals.dict()
        m["result"] = self.goals.generate_result()
        m["currentKey"] = self.currentKey
        m["maxDictId"] = self.current_dict_id
        m["start_time"] = self.start_time.timestamp() - 13039200
        m["forcedOptions"] = self.forcedOptions
        m["failures"] = self.failures

        return m

    def __str__(self):
        return lua.dumps(self.dict(), "mission", 1)

    def __repr__(self):
        rep = {"base": str(self), "options": self.options, "translation": self.translation}
        return repr(rep)


class MapResource:
    def __init__(self, mission: Mission):
        self.files = {}
        self.mission = mission

    def load_from_dict(self, _dict, zipf: zipfile.ZipFile, lang='DEFAULT'):
        _dict = _dict["mapResource"]

        for key in _dict:
            filename = _dict[key]
            extractedpath = zipf.extract('l10n/{lang}/{fn}'.format(lang=lang, fn=filename), tempfile.gettempdir())
            self.add_resource_file(extractedpath, lang, key)

    def add_resource_file(self, filepath, lang='DEFAULT', key=None):
        abspath = os.path.abspath(filepath)
        resource_key = key if key else "ResKey_" + str(self.mission.next_dict_id())
        if lang not in self.files:
            self.files[lang] = {}
        self.files[lang][abspath] = {
            "path": abspath,
            "reskey": resource_key
        }
        return resource_key

    def store(self, zipf: zipfile.ZipFile, lang='DEFAULT'):
        d = {}
        if lang in self.files:
            for x in self.files[lang]:
                mr = self.files[lang][x]
                filepath = mr["path"]
                if os.path.isabs(filepath):
                    nameinzip = os.path.basename(filepath)
                    zipf.write(filepath, "l10n/{lang}/{name}".format(lang=lang, name=nameinzip))
                    d[mr["reskey"]] = nameinzip

        return d
