
import json
import numpy as np
import requests
import openai
import os
from newspaper import Article
import re

# Define a class to generate queries based on a question
class QueryGenerator:
    # Construct a prompt for LLM based on a question
    def construct_prompt(self, question):
        return f"Extract the search query form this texttext: {question}Exaple output: Popularity of Python programming language in 2022"
    
    # Use LLM to generate a query from a question
    def __call__(self, token_cost_dict,model_dict,chain_id,question):
        tool = 'Google Search Query Generator'
        prompt = self.construct_prompt(question)
        messages = [{"role": "system", "content": prompt}]

        try:
            # Attempt package-relative import
            from . import models
        except ImportError:
            # Fall back to script-style import
            import models
        log_and_call_manager = models.LogAndCallManager(token_cost_dict)

        return models.llm_call(
            log_and_call_manager,
            model_dict,
            messages,
            tool=tool,
            chain_id=chain_id,
        )

# Define a class to perform a Google search and retrieve the content of the resulting pages    
class SearchEngine:
    # Perform a Google search using the SERPer API
    def search_google(self, query, gl='us', hl='en'):
        url = "https://google.serper.dev/search"
        payload = json.dumps({"q": query, "gl": gl, "hl": hl, "autocorrect": False})
        headers = {'X-API-KEY': os.environ['SERPER_API_KEY'], 'Content-Type': 'application/json'}

        response = requests.request("POST", url, headers=headers, data=payload)
        response = json.loads(response.text)
        return response
    
    # Download and parse an article from a URL using the Newspaper library
    def search_url(self, url, document_size=128):
        try:
            article = Article(url)
            article.download()
            article.parse()
        except:
            return []

        full_text = article.text.replace('\n', ' ')
        full_words = full_text.split(' ')
        # Create a list of "documents". Each "document" is a string that contains document_size consecutive words from the article.
        documents = [' '.join(full_words[i:i+document_size]) for i in range(0, len(full_words), document_size)]
        # Remove documents that are too short
        documents = [doc for doc in documents if len(doc) > 100]
        return documents
    
    # Perform a Google search and retrieve the content of the top results. Maximum word count is num_documents * context_size (default 7680)
    def __call__(self, query, num_documents=30, context_size=256):
        google_resp = self.search_google(query)
        
        documents = []
        top_links = []

        for i, resp in enumerate(google_resp['organic']):
            documents += self.search_url(resp['link'])
            if i < 5:
                top_links.append({'title': resp['title'], 'link': resp['link']})
            if len(documents) > num_documents:
                break

        documents = documents[:num_documents]
        return documents, top_links

# Define a class to retrieve the most relevant documents for a question
class DocumentRetriever:
    # Create a vector embedding of a text using OpenAI's 'text-embedding-ada-002' model
    def encode(self, input):
        resp = openai.Embedding.create(
            model = 'text-embedding-ada-002',
            input = input
        )

        return np.array([d['embedding'] for d in resp['data']])
    
    # Retrieve the most relevant documents for a question using vector embeddings
    def __call__(self, question, documents, k=5):
        question_embed = self.encode(question)
        document_embeds = self.encode(documents)

        # Compute the cosine similarity between the question embedding and the document embeddings
        scores = np.dot(question_embed, document_embeds.T)
        # Sort the documents by their cosine similarity to the question
        ranks = np.argsort(-scores)[0, :k].tolist()
        return [documents[r] for r in ranks]

# Define a class to generate an answer to a question based on a set of documents
class Reader:
    def construct_prompt(self, query, contexts):
        prompt = (
            "Summarise the below text into an answer for the following question:"
            "\n\n"
            f"Question: {query}"
            "\n\n"
            "Present this information in the most clear and comprehensible manner"
            "Be certain to incorporate all relevant facts and insights."
            "\n\n"
            "Text: "
            "\n\n"
        )

        for ctx in contexts:
            prompt += f'* {ctx}\n'

        return prompt

    # Use LLM to generate answer to a question based on a set of contexts
    def __call__(self,token_cost_dict,model_dict,chain_id,query, contexts):
        tool = 'Google Search Sumarizer'
        prompt = self.construct_prompt(query, contexts)
        search_messages = [{"role": "system", "content": prompt}]

        try:
            # Attempt package-relative import
            from . import models
        except ImportError:
            # Fall back to script-style import
            import models

        log_and_call_manager = models.LogAndCallManager(token_cost_dict)

        #replace llm in model_dict with 'gpt-3.5-turbo-16k'
        model_dict['llm']='gpt-3.5-turbo-16k'
        return models.llm_call(
            log_and_call_manager,
            model_dict,
            search_messages,
            tool=tool,
            chain_id=chain_id,
        )
    
class GoogleSearch:
    def __init__(self):
        self.query_generator = QueryGenerator()
        self.search_engine = SearchEngine()
        self.document_retriever = DocumentRetriever()
        self.reader = Reader()

    def _extract_search_query(self,response: str) -> str:
        return re.sub('\'|"', '',  response).strip()

    def __call__(self, token_cost_dict,model_dict,chain_id,question):
        question=self._extract_search_query(question)
        #query = self.query_generator(token_cost_dict,model_dict,chain_id,question)
        documents,top_links = self.search_engine(question)
        contexts = self.document_retriever(question, documents)
        answer = self.reader(token_cost_dict,model_dict,chain_id,question, contexts)

        return answer,top_links
