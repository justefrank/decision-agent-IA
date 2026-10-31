import { api } from '@/api/client';
import type { ConversationDetail, ConversationOut } from '@/api/types';

export const conversationsKey = ['conversations'] as const;
export const conversationKey = (id: string) => ['conversation', id] as const;

export const listConversations = () => api<ConversationOut[]>('/conversations?limit=100');
export const getConversation = (id: string) => api<ConversationDetail>(`/conversations/${id}`);
export const createConversation = () => api<ConversationOut>('/conversations', { method: 'POST', json: {} });
export const deleteConversation = (id: string) => api<void>(`/conversations/${id}`, { method: 'DELETE' });

export type FeedbackCategory =
  | 'chiffre_faux'
  | 'mauvaise_comprehension'
  | 'periode_ou_perimetre'
  | 'refus_injustifie'
  | 'autre';

export interface FeedbackInput {
  category: FeedbackCategory;
  comment?: string;
  consentQuestion: boolean;
}

export const postFeedback = (messageId: string, f: FeedbackInput) =>
  api<{ id: string; status: string; question_attached: boolean }>('/feedback', {
    method: 'POST',
    json: {
      message_id: messageId,
      category: f.category,
      comment: f.comment?.trim() ? f.comment.trim() : null,
      consent_question: f.consentQuestion,
    },
  });
