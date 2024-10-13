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
    preferred_industries = set([ind.lower() for ind in user['focus']])
    preferred_country = user['geographicPreferences'].lower()
    
    preferred_companies = []
    for _, company in companies_df.iterrows():
        company_industry = company['Industry'].lower()
        company_country = company['Country'].lower()
        
        industry_match = any(ind in company_industry for ind in preferred_industries)
        country_match = preferred_country == company_country

        if industry_match or country_match:
            preferred_companies.append(company['_id'])

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

    if(userProfile):
        user.update(userProfile)

    
    # Fetch companies from MongoDB
    companies = list(companies_collection.find({}))
    companies_df = pd.DataFrame(companies)
  
    interactions = []

    # Add interactions from 'history'
    for company_id in user['history']:
        interactions.append([current_user, company_id, 1])  # 1 means the user has interacted with this company

    # # Add interactions from 'saveList'
    for company_id in user['saveList']:
        interactions.append([current_user, company_id, 1])

    # Convert interactions to DataFrame
    interactions_df = pd.DataFrame(interactions, columns=['user_id', 'company_id', 'interaction'])

    # Pivot table to create the user-item matrix
    user_item_matrix = pd.pivot_table(interactions_df, index='user_id', columns='company_id', values='interaction', fill_value=0)

    # # Calculate cosine similarity between users
    if user_item_matrix.empty:
        return jsonify({"message": "You have not any interaction with our system!, Please explore more to get recomendations!"})

    user_similarity = cosine_similarity(user_item_matrix)
    user_similarity_df = pd.DataFrame(user_similarity, index=user_item_matrix.index, columns=user_item_matrix.index)

    # # # Calculate recommendations
    content_recommendations = get_content_based_recommendations(user, companies_df)
    final_recommendations = recommend_items(
        user_id=user['_id'],
        user_similarity_df=user_similarity_df,
        user_item_matrix=user_item_matrix,
        content_recommendations=content_recommendations
    )

    return jsonify(final_recommendations)

if __name__ == '__main__':
    app.run(debug=True, port=5000)
