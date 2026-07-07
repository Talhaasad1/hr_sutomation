"""
conftest.py
Patches pymongo.MongoClient with mongomock before any app module is imported,
so the test suite (and CI) runs against an in-memory MongoDB — no real
MongoDB server needed to validate the app's logic.
"""

import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
