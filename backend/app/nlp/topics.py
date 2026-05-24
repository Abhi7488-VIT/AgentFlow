from sklearn.feature_extraction.text import CountVectorizer
from sklearn.decomposition import LatentDirichletAllocation
import numpy as np
from app.core.logging import get_logger

logger = get_logger(__name__)

class TopicExtractor:
    def extract_topics(self, texts: list[str], n_topics: int = 5) -> list[dict]:
        if not texts or len(texts) < 3:
            return [{"topic_id": 0, "keywords": ["insufficient data"], "weight": 1.0}]
            
        try:
            vectorizer = CountVectorizer(max_df=0.95, min_df=2, stop_words='english')
            tf = vectorizer.fit_transform(texts)
            
            lda = LatentDirichletAllocation(n_components=min(n_topics, len(texts)), random_state=42)
            lda.fit(tf)
            
            feature_names = vectorizer.get_feature_names_out()
            topics = []
            
            # Calculate total weight for normalization
            topic_weights = np.sum(lda.transform(tf), axis=0)
            total_weight = np.sum(topic_weights)
            
            for topic_idx, topic in enumerate(lda.components_):
                top_features_ind = topic.argsort()[:-10 - 1:-1]
                top_features = [feature_names[i] for i in top_features_ind]
                
                weight = float(topic_weights[topic_idx] / total_weight) if total_weight > 0 else 0
                
                topics.append({
                    "topic_id": topic_idx,
                    "keywords": top_features,
                    "weight": weight
                })
                
            return topics
        except Exception as e:
            logger.error(f"Error extracting topics: {e}")
            return [{"topic_id": 0, "keywords": ["error_extracting_topics"], "weight": 1.0}]
