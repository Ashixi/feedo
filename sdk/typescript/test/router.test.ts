import { NodeRouter } from '../src/router';
import axios from 'axios';

jest.mock('axios');
const mockedAxios = axios as jest.Mocked<typeof axios>;

describe('NodeRouter', () => {
    beforeEach(() => {
        jest.clearAllMocks();
    });

    it('should return the fastest node when all nodes are up', async () => {
        const router = new NodeRouter({
            searchSeeds: ['http://node1', 'http://node2']
        });

        // Mock node1 to resolve faster than node2
        mockedAxios.get.mockImplementation((url) => {
            if (url === 'http://node1/explorer/stats') {
                return Promise.resolve({ data: {} });
            }
            if (url === 'http://node2/explorer/stats') {
                return new Promise((resolve) => setTimeout(() => resolve({ data: {} }), 100));
            }
            return Promise.reject(new Error('not found'));
        });

        const activeNode = await router.getSearchNode();
        expect(activeNode).toBe('http://node1');
    });

    it('should fallback to the working node if one is down', async () => {
        const router = new NodeRouter({
            searchSeeds: ['http://node1', 'http://node2']
        });

        // Mock node1 to fail
        mockedAxios.get.mockImplementation((url) => {
            if (url === 'http://node1/explorer/stats') {
                return Promise.reject(new Error('Network error'));
            }
            if (url === 'http://node2/explorer/stats') {
                return Promise.resolve({ data: {} });
            }
            return Promise.reject(new Error('not found'));
        });

        const activeNode = await router.getSearchNode();
        expect(activeNode).toBe('http://node2');
    });

    it('should fallback to the first seed if all nodes are down', async () => {
        const router = new NodeRouter({
            searchSeeds: ['http://node1', 'http://node2']
        });

        mockedAxios.get.mockRejectedValue(new Error('Network error'));

        // Silence the console.warn for the test
        const consoleSpy = jest.spyOn(console, 'warn').mockImplementation(() => {});

        const activeNode = await router.getSearchNode();
        expect(activeNode).toBe('http://node1'); // Falls back to first
        expect(consoleSpy).toHaveBeenCalled();
        consoleSpy.mockRestore();
    });
});
