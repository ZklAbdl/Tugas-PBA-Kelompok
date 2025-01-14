# -*- coding: utf-8 -*-
"""Word2Vec- LSTM

Automatically generated by Colab.

Original file is located at
    https://colab.research.google.com/drive/102zjCT1exDaLLPb7Iqd71-EKdzuqcLKu
"""

import os
import tarfile
import pandas as pd
import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, Dataset
from gensim.models import Word2Vec
from sklearn.model_selection import train_test_split
from torch.nn.utils.rnn import pad_sequence
from torch.optim import Adam
from tqdm import tqdm

# Extract AG News dataset
tar_path = "/content/ag_news_csv.tar.gz"
extracted_folder = "./ag_news_csv"

if not os.path.exists(extracted_folder):
    with tarfile.open(tar_path, "r:gz") as tar:
        tar.extractall(path=extracted_folder)
    print("Dataset extracted!")

# Load train and test data
train_data = pd.read_csv(os.path.join(extracted_folder, "/content/ag_news_csv/ag_news_csv/train.csv"), header=None)
test_data = pd.read_csv(os.path.join(extracted_folder, "/content/ag_news_csv/ag_news_csv/test.csv"), header=None)

# Rename columns for clarity
train_data.columns = ["label", "title", "description"]
test_data.columns = ["label", "title", "description"]

print("Train data sample:")
print(train_data.head())

# Combine title and description for text input
train_data["text"] = train_data["title"] + " " + train_data["description"]
test_data["text"] = test_data["title"] + " " + test_data["description"]

# Prepare labels (adjust to zero-indexed for PyTorch)
train_data["label"] -= 1
test_data["label"] -= 1

from gensim.utils import simple_preprocess
from collections import Counter

# Tokenize text
def preprocess_text(text):
    return simple_preprocess(text)

# Preprocess train and test text
train_tokens = train_data["text"].apply(preprocess_text)
test_tokens = test_data["text"].apply(preprocess_text)

# Combine all tokens for Word2Vec training
all_tokens = list(train_tokens) + list(test_tokens)

# Train Word2Vec model
word2vec_model = Word2Vec(sentences=all_tokens, vector_size=300, window=5, min_count=1, workers=4)
print("Word2Vec training complete!")

# Create word to index and embedding matrix
vocab = word2vec_model.wv.index_to_key
word2idx = {word: idx for idx, word in enumerate(vocab)}
embedding_matrix = torch.FloatTensor(word2vec_model.wv.vectors)

# Convert tokens to indices
def tokens_to_indices(tokens, word2idx):
    return [word2idx.get(word, 0) for word in tokens]

train_indices = [tokens_to_indices(tokens, word2idx) for tokens in train_tokens]
test_indices = [tokens_to_indices(tokens, word2idx) for tokens in test_tokens]

class TextDataset(Dataset):
    def __init__(self, data_indices, labels):
        self.data = [torch.tensor(seq, dtype=torch.long) for seq in data_indices]
        self.labels = torch.tensor(labels, dtype=torch.long)

    def __len__(self):
        return len(self.labels)

    def __getitem__(self, idx):
        return self.data[idx], self.labels[idx]

# Pad sequences
def collate_fn(batch):
    texts, labels = zip(*batch)
    texts = pad_sequence(texts, batch_first=True, padding_value=0)
    labels = torch.tensor(labels, dtype=torch.long)
    return texts, labels

# Prepare datasets and dataloaders
train_dataset = TextDataset(train_indices, train_data["label"].values)
test_dataset = TextDataset(test_indices, test_data["label"].values)

train_loader = DataLoader(train_dataset, batch_size=64, shuffle=True, collate_fn=collate_fn)
test_loader = DataLoader(test_dataset, batch_size=64, collate_fn=collate_fn)

class LSTMClassifier(nn.Module):
    def __init__(self, embedding_matrix, hidden_dim, output_dim):
        super(LSTMClassifier, self).__init__()
        num_embeddings, embedding_dim = embedding_matrix.shape
        self.embedding = nn.Embedding.from_pretrained(embedding_matrix, freeze=True)
        self.lstm = nn.LSTM(embedding_dim, hidden_dim, batch_first=True)
        self.fc = nn.Linear(hidden_dim, output_dim)
        self.dropout = nn.Dropout(0.5)

    def forward(self, x):
        embedded = self.embedding(x)
        lstm_out, _ = self.lstm(embedded)
        final_output = self.fc(self.dropout(lstm_out[:, -1, :]))
        return final_output

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
model = LSTMClassifier(embedding_matrix, hidden_dim=128, output_dim=4).to(device)

from sklearn.model_selection import train_test_split

# Bagi data menjadi train dan validation set
train_indices, val_indices, train_labels, val_labels = train_test_split(
    train_indices, train_data["label"].values, test_size=0.2, random_state=42
)

# Buat Dataset dan DataLoader untuk train dan validation
train_dataset = TextDataset(train_indices, train_labels)
val_dataset = TextDataset(val_indices, val_labels)

train_loader = DataLoader(train_dataset, batch_size=64, shuffle=True, collate_fn=collate_fn)
val_loader = DataLoader(val_dataset, batch_size=64, collate_fn=collate_fn)

# Model, Loss, dan Optimizer
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
model = LSTMClassifier(embedding_matrix, hidden_dim=128, output_dim=4).to(device)

criterion = nn.CrossEntropyLoss()
optimizer = Adam(model.parameters(), lr=0.001)

# Fungsi untuk menghitung loss pada validation set
def evaluate(model, val_loader, criterion, device):
    model.eval()
    val_loss = 0
    with torch.no_grad():
        for texts, labels in val_loader:
            texts, labels = texts.to(device), labels.to(device)
            outputs = model(texts)
            loss = criterion(outputs, labels)
            val_loss += loss.item()
    return val_loss / len(val_loader)

# Training loop dengan Train Loss dan Val Loss
for epoch in range(5):
    model.train()
    total_loss = 0

    # Training phase
    for texts, labels in tqdm(train_loader, desc=f"Epoch {epoch+1}"):
        texts, labels = texts.to(device), labels.to(device)
        optimizer.zero_grad()
        outputs = model(texts)
        loss = criterion(outputs, labels)
        loss.backward()
        optimizer.step()
        total_loss += loss.item()

    # Validation phase
    val_loss = evaluate(model, val_loader, criterion, device)

    # Print Train Loss dan Validation Loss
    print(f"Epoch {epoch+1}/{5}, Train Loss: {total_loss / len(train_loader):.4f}, Val Loss: {val_loss:.4f}")

# Evaluation
model.eval()
correct, total = 0, 0
with torch.no_grad():
    for texts, labels in test_loader:
        texts, labels = texts.to(device), labels.to(device)
        outputs = model(texts)
        _, preds = torch.max(outputs, 1)
        correct += (preds == labels).sum().item()
        total += labels.size(0)

print(f"Test Accuracy: {correct / total:.4f}")