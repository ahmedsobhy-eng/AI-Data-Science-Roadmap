import requests

# Define sensitive user data (username and password)
my_data = {"username": "Ahmed", "password": "SuperSecretPassword123"}

# ==========================================
# 1. Sending data using GET method (Unsafe for sensitive data ❌)
# ==========================================
url_get = 'https://httpbin.org/get'

# Pass data to the 'params' argument to append it to the URL
r_get = requests.get(url_get, params=my_data)

print("GET URL:")
print(r_get.url) 
# Security risk: The output will show credentials exposed in the URL like this:
# https://httpbin.org/get?username=Ahmed&password=SuperSecretPassword123

print("-" * 40)

# ==========================================
# 2. Sending data using POST method (Safe for sensitive data ✅)
# ==========================================
url_post = 'https://httpbin.org/post'

# Pass data to the 'data' argument to hide it securely inside the request body
r_post = requests.post(url_post, data=my_data)

print("POST URL:")
print(r_post.url)
# The URL remains clean and data is secured in the request body:
# https://httpbin.org/post