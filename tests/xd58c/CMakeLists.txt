cmake_minimum_required(VERSION 3.20.0)

find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})
project(xd58c_tests)

zephyr_include_directories(.)
target_sources(app PRIVATE xd58c_test.c)
