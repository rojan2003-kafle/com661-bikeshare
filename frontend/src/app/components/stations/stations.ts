import { Component, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { StationData } from '../../services/station-data';

@Component({
  imports: [RouterLink],
  selector: 'app-stations',
  styleUrl: './stations.css',
  templateUrl: './stations.html',
})
export class Stations {
  station_list = signal<any[]>([]);
  page = signal(1);
  lastPage = signal(1);

  constructor(private stationData: StationData) { }

  ngOnInit() {
    this.loadPage();
  }

  loadPage() {
    this.stationData.getStations(this.page()).subscribe(response => {
      this.station_list.set(response.data);
      this.lastPage.set(response.total_pages);
    });
  }

  nextPage() {
    if (this.page() < this.lastPage()) {
      this.page.set(this.page() + 1);
      this.loadPage();
    }
  }

  previousPage() {
    if (this.page() > 1) {
      this.page.set(this.page() - 1);
      this.loadPage();
    }
  }
}