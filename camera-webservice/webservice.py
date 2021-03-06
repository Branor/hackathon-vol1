#!/usr/bin/python
# pip install flask flask-restful pillow boto3 json elasticsearch
from flask import Flask, jsonify, abort, make_response, request
from flask_restful import Api, Resource, reqparse, fields, marshal
import time, socket, uuid, os, boto3, json, sys, threading
from datetime import datetime
import uuid
from elasticsearch import Elasticsearch
from couchbase.cluster import Cluster
from couchbase.cluster import PasswordAuthenticator
from couchbase.n1ql import N1QLQuery
if os.name == 'nt':
	from PIL import Image

# Supress SSL cert errors
import botocore.vendored.requests
from botocore.vendored.requests.packages.urllib3.exceptions import InsecureRequestWarning
botocore.vendored.requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

def open_couchbase_bucket(cluster, bucket, username, password) :
	cluster = Cluster(cluster)
	authenticator = PasswordAuthenticator(username, password)
	cluster.authenticate(authenticator)
	bucket = cluster.open_bucket(bucket)
	return bucket

# Get own IP address
def get_ip_address():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(("8.8.8.8", 80))
    return s.getsockname()[0]

# Create index with specific field settings
def create_es_indicies():
	es = Elasticsearch([conf['elasticsearch_host']])
	# Create photo index if needed
	if not es.indices.exists('photo'):
		# index settings
		settings = {
	    	"mappings": {
				"info": {
	            	"properties": {
					        "camera_name" : {"type": "string", "fields": {"raw" : {"type": "string","index": "not_analyzed"}}},
							"photo_url" : {"type": "string", "fields": {"raw" : {"type": "string","index": "not_analyzed"}}}
	        		}
				}
			}
		}
		es.indices.create(index='photo', ignore=400, body=settings)
	
	# Create camera index if needed
	if not es.indices.exists('camera'):
		es.indices.create(index='camera', ignore=400)

# Update camera index every 60s as a heartbeat to determine 'active' cameras
def heartbeat_es_index(elasticsearch_host, ip_address, camera_name):
	while (1):
		es = Elasticsearch([conf['elasticsearch_host']])
		ts = round(time.time())
		res = es.index(index='camera', doc_type='camera_info', id=ip_address, body={'camera_name': conf['camera_name'], 'epoch_timestamp': ts})
		if 'created' or 'updated' in res:
			print ('## ElasticSearch heartbeat saved at: _index=[' + res['_index'] + '], _id=[' + res['_id'] + '], epoch_timestamp=[' + str(ts) + ']')
		else:
			print ('## ElasticSearch heartbeat update failed')
		time.sleep(60)

		# Update camera index every 60s as a heartbeat to determine 'active' cameras
def heartbeat_cb_bucket(ip_address, camera_name):
	while (1):
		ts = round(time.time())
		key = 'camera::' + ip_address
		camera_info = {'camera_name': conf['camera_name'], 'epoch_timestamp': ts, 'camera_ip': ip_address}
		res = bucket.upsert(key, camera_info)
		print ('## Couchbase heartbeat saved at: id=[' + key + '], epoch_timestamp=[' + str(ts) + ']')
		time.sleep(60)


class RootAPI(Resource):

	def get(self):
		return make_response(jsonify({'status': 200, 'message' : "camera-webservice is running"}), 200)

class TakePhotoAPI(Resource):

	# route GET requests to POST (for debugging only)
	def get(self):
		return self.post()

	def post(self):
		# Maybe do something with post variables later...
		try:
			req = request.get_json(force=True)
		except:
			req = dict()
			pass

		# Take photo
		filename = str(uuid.uuid4())
		if os.name == 'nt':
			os.system(conf['camera_command'] + ' ' + filename)
			im = Image.open(filename)
			im.save(filename + '.jpg', 'JPEG')
			os.remove(filename)
			filename += '.jpg'
		else:
			filename += '.jpg'
			os.system(conf['camera_command'] + ' ' + filename)

		# Save filesize for metadata posted to ES
		filesize = os.path.getsize(filename)

		# For testing to avoid S3 and ES posting
		#  curl -s -H "Content-Type: application/json" -X POST -d '{"test":true}' http://localhost:8080/take_photo
		try:
			if req['test'] is True:
				print ('## Photo saved locally at: ' + filename)
				return make_response(jsonify({'filesize': filesize, 'filename': filename}))
		except:
			pass

		# For testing to skip S3 posting
		#  curl -s -H "Content-Type: application/json" -X POST -d '{"skip_s3":true}' http://localhost:8080/take_photo

		if 'skip_s3' in req and req['skip_s3'] is True:
			url = "http://localhost/test.jpg"
		else:
			# Upload to S3 endpoint
			session = boto3.session.Session(aws_access_key_id=conf['access_key'], aws_secret_access_key=conf['secret_access_key'])
			s3 = session.resource(service_name='s3', endpoint_url=conf['endpoint'], verify=False)
			obj = s3.Object(conf['bucket'], filename)
			data = open(filename, 'rb')
			obj.put(Body=data, ContentType='image/jpeg')
			data.close()
			os.remove(filename)
			url = conf['endpoint'] + "/" + conf['bucket'] + "/" + filename
			print ('## Photo saved at: ' + url)

		# Post image taken to ES; let id be completed by ES
		es = Elasticsearch([conf['elasticsearch_host']])
		## Create special datetime format that ES expects
		now = datetime.utcnow()
		ts = now.strftime("%Y-%m-%dT%H:%M:%S") + ".%03d" % (now.microsecond / 1000) + "Z"
		res_body = { 'timestamp': ts, 'url': url, 'filesize': filesize, 'camera_name': conf['camera_name'], 'camera_ip': ip_address}
		res = es.index(index='photo', doc_type='info', body=res_body)
		if res['created']:
			print ('## ElasticSearch saved at:  _index=[' + res['_index'] + '], _id=[' + res['_id'] + ']')
		else:
			print ('## ElasticSearch update failed')

		key = str(uuid.uuid4())
		res = bucket.upsert(key, res_body)
		print ('## Couchbase saved at:  id=[' + key + ']')

		# Return success
		return make_response(jsonify(res_body), 200)

# Setup Flask and REST Endpoint
app = Flask(__name__, static_url_path="")
api = Api(app)

api.add_resource(RootAPI, '/')
api.add_resource(TakePhotoAPI, '/take_photo')

global bucket

if __name__ == '__main__':

	print ('## Starting camera-webservice')
	try:
		with open('config.json') as data_file:
			conf = json.load(data_file)
			conf['camera_name']
			conf['endpoint']
			conf['bucket']
			conf['access_key']
			conf['secret_access_key']
			conf['elasticsearch_host']
			conf['camera_command']
			conf['couchbase_host']
			conf['couchbase_bucket']
			conf['couchbase_username']
			conf['couchbase_password']
	except Exception as e:
		sys.stderr.write('FATAL: Cannot open or parse configuration file : ' + str(e) + '\n\n')
		exit()

	try:
		global bucket
		bucket = open_couchbase_bucket(conf['couchbase_host'], conf['couchbase_bucket'], conf['couchbase_username'], conf['couchbase_password'])
	except Exception as e:
		sys.stderr.write('FATAL: Cannot open Couchbase bucket : ' + str(e) + '\n\n')
		exit()

	ip_address = get_ip_address()
	#ip_address = '1.2.3.4'
	create_es_indicies()
	t_es = threading.Thread(target=heartbeat_es_index, args=(conf['elasticsearch_host'], ip_address, conf['camera_name']))
	t_es.daemon = True
	t_es.start()

	t_cb = threading.Thread(target=heartbeat_cb_bucket, args=(ip_address, conf['camera_name']))
	t_cb.daemon = True
	t_cb.start()

	print ('## camera-webservice will be reachable at http://'+ ip_address + ':8080')
	app.run(host='0.0.0.0', port=8080, debug=True, use_reloader=False)
