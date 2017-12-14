require 'sinatra'
require 'rest-client'


def execute_query(query)
  get_rest_response(query, ENV['COUCHBASE_REST'], ENV['COUCHBASE_USERNAME'], ENV['COUCHBASE_PASSWORD'])
end

def get_rest_response(payload, path, username, password)
  response = RestClient::Request.new({
      method: :post,
      url: path,
      user: username,
      password: password,
      payload: 'statement='+payload
    }).execute

    results = JSON.parse(response.to_str)
    results['results']
end

# Show welcome page
get "/" do

  ts = Time.now.to_i
  @cameras = []
  response = execute_query("SELECT camera_ip, camera_name, epoch_timestamp FROM default WHERE epoch_timestamp is valued")
  response.each do |r|
    status = (ts - r['epoch_timestamp'].to_i < 120)
    @cameras << {:name => r['camera_name'], :ip => r['camera_ip'], :online => status}
  end

  # Get 4 latest photos
  @photos = []
  response = execute_query("SELECT url, camera_name, timestamp FROM default WHERE timestamp is valued ORDER BY timestamp desc LIMIT 4")
  response.each do |r|
    @photos << {:url => r['url'], :camera_name => r['camera_name'], :timestamp => r['timestamp']}
  end

  haml :index
end

# Show take photo page
get "/take_photo/:camera_ip" do
  camera_ip = params[:camera_ip]
  response = RestClient::Request.execute(method: :post, url: "http://#{camera_ip}:8080/take_photo", timeout: 10)
  @image_url = response.body['url'].to_s
  @timestamp = response.body['timestamp'].to_s

  haml :show_photo
end
