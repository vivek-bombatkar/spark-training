#!/usr/bin/python
# -*- coding: utf-8 -*-

import optparse
import logging

from pyspark.java_gateway import launch_gateway
from pyspark import SparkContext
from pyspark import SparkConf

from weather import StationData
from weather import WeatherData
from weather import WeatherMinMax
from weather import reduce_wmm
from weather import combine_wmm


logger = logging.getLogger(__name__)
gateway = None


def get_py4j_gateway():
    """
    This creates the Py4j gateway used by Spark. We create it here, so we can silence logging
    activity.
    """
    global gateway
    if not gateway:
        logger.info("Creating Py4j gateway")
        gateway = launch_gateway()
        jvm = gateway.jvm

        # Reduce verbosity of logging
        l4j = jvm.org.apache.log4j
        l4j.LogManager.getRootLogger(). setLevel( l4j.Level.WARN )
        l4j.LogManager.getLogger("org"). setLevel( l4j.Level.WARN )
        l4j.LogManager.getLogger("akka").setLevel( l4j.Level.WARN )

    return gateway


def create_context(appName):
    """
    Creates Spark HiveContext, with WebUI disabled and logging minimized
    """
    logger.info("Creating Spark context - may take some while")

    # Create SparkConf with UI disabled
    conf = SparkConf()
    conf.set("spark.hadoop.validateOutputSpecs", "false")
    #conf.set('spark.ui.enabled','false')
    #conf.set('spark.executor.memory','8g')
    #conf.set('spark.executor.cores','6')

    gateway = get_py4j_gateway()
    sc = SparkContext(appName=appName, conf=conf, gateway=gateway)
    return sc


def parse_options():
    """
    Parses all command line options and returns an approprate Options object
    :return:
    """

    parser = optparse.OptionParser(description='PySpark WordCount.')
    parser.add_option('-s', '--stations', action='store', nargs=1, help='Input file or directory containing station data')
    parser.add_option('-w', '--weather', action='store', nargs=1, help='Input file or directory containing weather data')
    parser.add_option('-o', '--output', action='store', nargs=1, help='Output file or directory')

    (opts, args) = parser.parse_args()

    return opts


def main():
    opts = parse_options()

    logger.info("Creating Spark Context")
    sc = create_context(appName="WordCount")

    logger.info("Starting processing")

    stations = sc.textFile(opts.stations) \
        .map(lambda line: StationData(line))

    weather = sc.textFile(opts.weather) \
        .map(lambda line: WeatherData(line))

    station_index = stations.keyBy(lambda data: data.usaf + data.wban)
    weather_index = weather.keyBy(lambda data: data.usaf + data.wban)

    # joined_weather will contain tuples (usaf_wban, (weather, station))
    # i.e. [0] = usaf_wban
    #      [1][0] = weather
    #      [1][1] = station
    joined_weather = weather_index.join(station_index)

    # Helper method for extracting (country, date) and weather
    def extract_country_year_weather(data):
        return ((data[1][1].country, data[1][0].date[0:4]), data[1][0])

    # Now extract country and year using the function above
    weather_per_country_and_year = \
        joined_weather.map(extract_country_year_weather)

    # Aggregate min/max information per year and country
    weather_minmax = weather_per_country_and_year \
        .aggregateByKey(WeatherMinMax(),reduce_wmm, combine_wmm)

    # Helper method for pretty printing
    def format_result(row):
        (k,v) = row
        country = k[0]
        year = k[1]
        minT = v.minTemperature or 0.0
        maxT = v.maxTemperature or 0.0
        minW = v.minWindSpeed or 0.0
        maxW = v.maxWindSpeed or 0.0
        line = "%s,%s,%f,%f,%f,%f" % (country, year, minT, maxT, minW, maxW)
        return line.encode('utf-8')

    # Store results
    weather_minmax \
        .map(format_result) \
        .saveAsTextFile(opts.output)

    logger.info("Successfully finished processing")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    logging.getLogger('').setLevel(logging.INFO)

    logger.info("Starting main")
    main()
    logger.info("Successfully finished main")
