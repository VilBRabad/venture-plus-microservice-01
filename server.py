from functools import wraps
from flask import Flask, request, jsonify
import pandas as pd
from sklearn.metrics.pairwise import cosine_similarity
from pymongo import MongoClient
from dotenv import load_dotenv
from flask_cors import CORS
from bson.objectid import ObjectId
import jwt
import os
import awsgi
import nltk
from nltk.sentiment.vader import SentimentIntensityAnalyzer

load_dotenv()

MONGODB_URL = os.getenv("DATABASE_URI")
MONGODB_DATABASE = os.getenv("DB_NAME")
SECRET_KEY = os.getenv("SECRET_KEY")

app = Flask(__name__)
CORS(app)

try:
    # MongoDB connection setup
    client = MongoClient(MONGODB_URL)
    db = client[MONGODB_DATABASE]
    companies_collection = db['organizations']
    user_collection = db['investors']
    user_profile_collection = db['investorprofiles']
    print("MongoDB connection successful")
except Exception as e:
    print(f"Error connecting to MongoDB: {e}")

def get_content_based_recommendations(user, companies_df):
    preferred_industries = set(user['focus'])
    preferred_country = user['geographicPreferences']
    
    preferred_companies = []

    # Loop through the companies to find matches
    for _, company in companies_df.iterrows():
        company_industry = company['Industry']
        company_country = company['Country']
        # print(company_industry)
        
        # Match both industry and country
        # print(type(company_industry))
        if isinstance(company_industry, str):
            industry_match = any(ind in company_industry.lower() for ind in preferred_industries)
        else:
            industry_match = False  # No match if 'Industry' is not a string

        country_match = preferred_country.lower() == company_country.lower()

        # Print details of the matching process
        # print(f"Checking company: {company['Company']}")
        # print(f"Industry match: {industry_match}, Country match: {country_match}")
        
        # Add the company if both industry and country match
        if industry_match or country_match:
            preferred_companies.append(company['_id'])

    # print("Filtered preferred companies based on content:", preferred_companies)
    return preferred_companies

def recommend_items(user_id, user_similarity_df, user_item_matrix, content_recommendations):
    similar_users = user_similarity_df[user_id].sort_values(ascending=False)[1:]
 
    collaborative_recommendations = set()
    for similar_user in similar_users.index:
        user_interactions = user_item_matrix.loc[similar_user]
        for company_id in user_interactions[user_interactions > 0].index:
            if user_item_matrix.loc[user_id][company_id] == 0:
                collaborative_recommendations.add(company_id)
    
    final_recommendations = list(set(collaborative_recommendations) | set(content_recommendations))
    return final_recommendations


def tokenRequired(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        
        if 'Authorization' in request.headers:
            token = request.headers['Authorization'].split(" ")[1]  # Bearer token
        
        if not token:
            return jsonify({"message": "Token is missing!"}), 403

        try:
            # Decode the token using the secret key
            # print("SECRET_KEY: ", SECRET_KEY)
            data = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
            # data = jwt.decode()
            current_user = data['_id']  # Access your user data from the token payload
            # print("User: ", data)
        except jwt.ExpiredSignatureError:
            return jsonify({"message": "Token has expired!"}), 401
        except jwt.InvalidTokenError:
            return jsonify({"message": "Invalid token!"}), 401

        return f(current_user, *args, **kwargs)

    return decorated

@app.route('/recommend', methods=['POST'])
@tokenRequired
def recommend(current_user):
    if not current_user: 
        return jsonify({"message": "Un-authorised rerquest!"})

    user = user_collection.find_one({"_id": ObjectId(current_user)})
    userProfile = user_profile_collection.find_one({"investor": ObjectId(current_user)})
    user['password'] = None
    user['refreshToken'] = None

    if user:
        user['_id'] = str(user['_id'])
        user['profile'] = str(user['profile'])

    if userProfile:
        del userProfile['_id']
        del userProfile['investor'] 
        user.update(userProfile)

        # print("user: ", user)

    
    # Fetch companies from MongoDB
    companies = list(companies_collection.find({}))
    # print(len(companies))
    for company in companies:
        company['_id'] = str(company['_id'])

    companies_df = pd.DataFrame(companies)
  
    interactions = []

    # Add interactions from 'history'
    for company_id in user['history']:
        only_id = company_id['_id']
        interactions.append([current_user, str(only_id), 1])  # 1 means the user has interacted with this company

    # # Add interactions from 'saveList'
    for company_id in user['saveList']:
        interactions.append([current_user, str(company_id), 1])

    # print("INTERACTION: ", interactions)

    # Convert interactions to DataFrame
    interactions_df = pd.DataFrame(interactions, columns=['user_id', 'company_id', 'interaction'])

    # Pivot table to create the user-item matrix
    user_item_matrix = pd.pivot_table(interactions_df, index='user_id', columns='company_id', values='interaction', fill_value=0)

    # print(user_item_matrix.head)
    # # # Calculate cosine similarity between users
    if user_item_matrix.empty:
        return jsonify({"message": "You have not any interaction with our system!, Please explore more to get recomendations!", "data": []})

    user_similarity = cosine_similarity(user_item_matrix)
    user_similarity_df = pd.DataFrame(user_similarity, index=user_item_matrix.index, columns=user_item_matrix.index)

    # print(user_similarity_df.head)
    # # # # Calculate recommendations
    content_recommendations = get_content_based_recommendations(user, companies_df)
    # print("Content Rec: ", content_recommendations)
    final_recommendations = recommend_items(
        user_id=user['_id'],
        user_similarity_df=user_similarity_df,
        user_item_matrix=user_item_matrix,
        content_recommendations=content_recommendations
    )
    print("LENGTH: ", len(final_recommendations))
    return jsonify({"data": final_recommendations})


nltk.download('vader_lexicon')

@app.route("/analyze-review", methods=["POST"])
def analyze_review():
    data = request.get_json()
    text = data.get("text", "")

    if not text:
        return jsonify({"status": 400, "message": "No text provided"})

    analyzer = SentimentIntensityAnalyzer()
    scores = analyzer.polarity_scores(text)
    sentiment = 1 if scores['pos'] > 0 else 0

    return jsonify({"text": text, "sentiment": sentiment, "scores": scores})


@app.route('/')
def home():
    return jsonify({"message": "home page..."})



# def lambda_handler(event, context):
#     try:
#         if 'httpMethod' not in event:
#             raise ValueError("Missing 'httpMethod' in the event")
        
#         return awsgi.response(app, event, context, base64_content_types={"image/png"})
    
#     except Exception as e:
#         print(f"Error: {e}")
#         return {
#             "statusCode": 500,
#             "body": f"Error: {str(e)}"
#         }

if __name__ == '__main__':
    app.run(host="0.0.0.0", debug=True, port=5000)