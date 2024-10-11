from flask import Flask, request, jsonify
import pandas as pd
from sklearn.metrics.pairwise import cosine_similarity
from pymongo import MongoClient
from dotenv import load_dotenv
import os

load_dotenv()

MONGODB_URL = os.getenv("MONGODB_URL")
MONGODB_DATABASE = os.getenv("MONGODB_DATABASE")

app = Flask(__name__)

# MongoDB connection setup
client = MongoClient(MONGODB_URL)
db = client[MONGODB_DATABASE]
companies_collection = db['organizations']

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

@app.route('/recommend', methods=['POST'])
def recommend():
    data = request.get_json()
    user_data = data['user']
    user_df = pd.DataFrame([user_data])
    
    # Fetch companies from MongoDB
    companies = list(companies_collection.find({}))
    companies_df = pd.DataFrame(companies)
  
    # Create a user-item interaction matrix
    user_id = user_data['_id']
    interactions = []

    # Add interactions from 'history'
    for company_id in user_data['history']:
        interactions.append([user_id, company_id, 1])  # 1 means the user has interacted with this company

    # Add interactions from 'saveList'
    for company_id in user_data['saveList']:
        interactions.append([user_id, company_id, 1])

    # Convert interactions to DataFrame
    interactions_df = pd.DataFrame(interactions, columns=['user_id', 'company_id', 'interaction'])

    # Pivot table to create the user-item matrix
    user_item_matrix = pd.pivot_table(interactions_df, index='user_id', columns='company_id', values='interaction', fill_value=0)

    # Calculate cosine similarity between users
    user_similarity = cosine_similarity(user_item_matrix)
    user_similarity_df = pd.DataFrame(user_similarity, index=user_item_matrix.index, columns=user_item_matrix.index)

    # Calculate recommendations
    content_recommendations = get_content_based_recommendations(user_data, companies_df)
    final_recommendations = recommend_items(
        user_id=user_data['_id'],
        user_similarity_df=user_similarity_df,
        user_item_matrix=user_item_matrix,
        content_recommendations=content_recommendations
    )

    return jsonify(final_recommendations)

if __name__ == '__main__':
    app.run(debug=True)
