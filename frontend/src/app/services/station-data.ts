import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';

@Injectable({
  providedIn: 'root'
})
export class StationData {
  private apiUrl = 'http://localhost:5001/api/v1.0';
  pageSize: number = 6;

  constructor(private http: HttpClient) { }

  getStations(page: number) {
    return this.http.get<any>(`${this.apiUrl}/stations?pn=${page}&ps=${this.pageSize}`);
  }

  getStation(id: any) {
    return this.http.get<any>(`${this.apiUrl}/stations/${id}`);
  }
}